"""
HoverMind – Smart AI Pointer for Windows
=========================================
Hold **Alt + Shift** and hover the mouse over anything on screen to get an
instant AI-generated explanation displayed in a floating tooltip.

Architecture
------------
ScreenCapture   – Grabs a 500×500 px snippet around the cursor (DPI-aware).
AIAnalyzer      – Sends the snippet to the Google Gemini Vision API and
                  returns a short natural-language explanation.
FloatingTooltip – PyQt6 frameless, translucent, always-on-top overlay window
                  that displays the AI response next to the cursor.
MainController  – Ties the pynput hotkey listener to the capture → analyse →
                  display pipeline and owns the Qt application event loop.

Requirements
------------
See requirements.txt.  Set GEMINI_API_KEY in a .env file (see .env.example).

Windows-specific notes
----------------------
* DPI Awareness: Python 3.8+ embeds an application manifest that declares
  DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 before any user code runs.  Every
  coordinate is therefore in physical pixels and every mss capture matches them
  exactly.  Because the manifest already owns the DPI setting, Qt6's attempt to
  call SetProcessDpiAwarenessContext at QApplication startup is rejected by
  Windows (ERROR_ACCESS_DENIED).  The resulting ``qt.qpa.window`` warning is
  suppressed via QT_LOGGING_RULES in main() since the DPI behaviour is correct.
* Always-on-top: Qt.WindowType.WindowStaysOnTopHint combined with
  Qt.WindowType.Tool prevents the tooltip from stealing focus or appearing in
  the taskbar.
* mss is used for capture because it talks directly to the Win32 GDI API,
  making it 3-10× faster than PIL.ImageGrab on Windows.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import sys
import threading
from abc import ABC, abstractmethod
from typing import ClassVar, Optional, Type

# ---------------------------------------------------------------------------
# Third-party imports
# ---------------------------------------------------------------------------
import mss
import mss.tools
import requests
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from pynput import keyboard as pynput_keyboard
from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap, QScreen
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hovermind")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

SNIPPET_SIZE: int = 500          # width/height of the captured region in px
TOOLTIP_MAX_WIDTH: int = 420     # maximum pixel width of the tooltip widget
TOOLTIP_OFFSET_X: int = 20       # horizontal offset from the cursor tip
TOOLTIP_OFFSET_Y: int = 20       # vertical offset from the cursor tip
HOTKEY_KEYS: frozenset = frozenset(
    {pynput_keyboard.Key.alt, pynput_keyboard.Key.shift}
)
# pynput reports left/right variants (e.g. Key.alt_l) rather than the generic
# Key.alt / Key.shift on most platforms.  Normalize them so the hotkey check
# works regardless of which physical key the user presses.
_KEY_NORMALIZE: dict[pynput_keyboard.Key, pynput_keyboard.Key] = {
    pynput_keyboard.Key.alt_l: pynput_keyboard.Key.alt,
    pynput_keyboard.Key.alt_r: pynput_keyboard.Key.alt,
    pynput_keyboard.Key.alt_gr: pynput_keyboard.Key.alt,
    pynput_keyboard.Key.shift_l: pynput_keyboard.Key.shift,
    pynput_keyboard.Key.shift_r: pynput_keyboard.Key.shift,
}
AI_PROMPT: str = (
    "Briefly explain what the user is pointing at in the center of this "
    "image. If it's code, explain it. If it's an image, describe it. If "
    "it's a UI element, state its function. Keep it under 3 sentences."
)
DEBOUNCE_MS: int = int(os.environ.get("DEBOUNCE_MS", "800"))
HOVERMIND_LOG_FILE: str = os.environ.get("HOVERMIND_LOG_FILE", "")
AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "gemini").lower()
AI_MODEL: str = os.environ.get("AI_MODEL", "")


# ---------------------------------------------------------------------------
# Optional file logging
# ---------------------------------------------------------------------------

def _setup_file_logging() -> None:
    """Attach a :class:`logging.FileHandler` when ``HOVERMIND_LOG_FILE`` is set.

    The handler writes to the path given by the environment variable at the
    same log level and format as the console handler so both outputs are
    consistent.
    """
    if not HOVERMIND_LOG_FILE:
        return
    handler = logging.FileHandler(HOVERMIND_LOG_FILE, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)
    logger.info("File logging enabled: %s", HOVERMIND_LOG_FILE)


# ===========================================================================
# ScreenCapture
# ===========================================================================
class ScreenCapture:
    """Captures a square region of the screen centred on the cursor.

    The captured area is SNIPPET_SIZE × SNIPPET_SIZE physical pixels.  The
    region is clamped to the screen boundaries so it never wraps off-edge.

    Parameters
    ----------
    snippet_size:
        Side length (in physical pixels) of the square capture region.
        Defaults to the module-level ``SNIPPET_SIZE`` constant.
    """

    def __init__(self, snippet_size: int = SNIPPET_SIZE) -> None:
        self._snippet_size = snippet_size

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def capture_around(self, x: int, y: int) -> Image.Image:
        """Return a PIL Image centred on (*x*, *y*).

        Parameters
        ----------
        x, y:
            Cursor position in physical (DPI-aware) screen pixels.

        Returns
        -------
        PIL.Image.Image
            SNIPPET_SIZE × SNIPPET_SIZE RGB image (or smaller if near a
            screen edge).
        """
        half = self._snippet_size // 2
        left = x - half
        top = y - half

        with mss.mss() as sct:
            # mss.monitors[0] is the virtual bounding box of all monitors.
            monitor_all = sct.monitors[0]
            screen_left = monitor_all["left"]
            screen_top = monitor_all["top"]
            screen_right = screen_left + monitor_all["width"]
            screen_bottom = screen_top + monitor_all["height"]

            # Clamp the capture region to the screen boundaries.
            left = max(left, screen_left)
            top = max(top, screen_top)
            right = min(left + self._snippet_size, screen_right)
            bottom = min(top + self._snippet_size, screen_bottom)

            region = {
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
            }
            screenshot = sct.grab(region)

        # mss returns BGRA; convert to RGB for compatibility with Pillow /
        # the Gemini API image encoder.
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img

    def capture_as_bytes(self, x: int, y: int, fmt: str = "PNG") -> bytes:
        """Capture and encode the region to *bytes* in the given format.

        Parameters
        ----------
        x, y:
            Cursor position in physical pixels.
        fmt:
            Pillow image format string, e.g. ``"PNG"`` or ``"JPEG"``.

        Returns
        -------
        bytes
            Encoded image bytes suitable for transmission to an API.
        """
        img = self.capture_around(x, y)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()


# ===========================================================================
# Analyzers
# ===========================================================================
class AnalyzerBase(ABC):
    """Abstract base class for all AI provider integrations."""

    provider_name: ClassVar[str]
    default_model: ClassVar[str]

    def __init__(self, model_name: Optional[str] = None) -> None:
        provider = getattr(self, "provider_name", None)
        default_model = getattr(self, "default_model", None)
        if not provider or not isinstance(provider, str):
            raise NotImplementedError(
                "Subclasses must define provider_name."
            )
        if not default_model or not isinstance(default_model, str):
            raise NotImplementedError(
                "Subclasses must define default_model."
            )
        self._model_name = model_name or self.default_model

    @abstractmethod
    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Return a short textual explanation for the given image bytes."""


class GeminiAnalyzer(AnalyzerBase):
    """Google Gemini Vision analyzer."""

    provider_name = "gemini"
    default_model = "gemini-1.5-flash"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        super().__init__(model_name=model_name)
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or pass it explicitly."
            )
        self._client = genai.Client(api_key=resolved_key)

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        try:
            image_part = genai_types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            )
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=[image_part, AI_PROMPT],
            )
            return response.text.strip()
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            return f"⚠ AI analysis failed: {exc}"


class OpenAIAnalyzer(AnalyzerBase):
    """OpenAI GPT-4o Vision analyzer."""

    provider_name = "openai"
    default_model = "gpt-4o"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        super().__init__(model_name=model_name)
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or pass it explicitly."
            )
        from openai import OpenAI  # lazy import so tests can stub

        self._client = OpenAI(api_key=resolved_key)

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": AI_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Explain what is shown in this image.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{encoded}"
                                },
                            },
                        ],
                    },
                ],
            )
            try:
                choice = response.choices[0]
                message = getattr(choice, "message", choice)
                content = message.content
            except Exception as exc:
                logger.error("OpenAI response format error: %s", exc)
                return "⚠ AI analysis failed: malformed response"
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        maybe_text = part.get("text", "")
                        if maybe_text:
                            text_parts.append(str(maybe_text))
                    elif hasattr(part, "text"):
                        text_parts.append(str(part.text))
                    else:
                        text_parts.append(str(part))
                text = " ".join(tp for tp in text_parts if tp).strip()
            else:
                text = str(content).strip()
            return text or "⚠ AI analysis returned no text."
        except Exception as exc:
            logger.error("OpenAI API error: %s", exc)
            return f"⚠ AI analysis failed: {exc}"


class AnthropicAnalyzer(AnalyzerBase):
    """Anthropic Claude Vision analyzer."""

    provider_name = "anthropic"
    default_model = "claude-3-5-sonnet-latest"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        super().__init__(model_name=model_name)
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file or pass it explicitly."
            )
        from anthropic import Anthropic  # lazy import

        self._client = Anthropic(api_key=resolved_key)

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        try:
            response = self._client.messages.create(
                model=self._model_name,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": AI_PROMPT},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": encoded,
                                },
                            },
                        ],
                    }
                ],
            )
            try:
                content = response.content
            except Exception as exc:
                logger.error("Anthropic response format error: %s", exc)
                return "⚠ AI analysis failed: malformed response"
            texts = []
            for part in content:
                if isinstance(part, dict):
                    text_val = part.get("text", "")
                    if text_val:
                        texts.append(str(text_val))
                elif hasattr(part, "text"):
                    texts.append(str(part.text))
            text = " ".join(t for t in texts if t).strip()
            return text or "⚠ AI analysis returned no text."
        except Exception as exc:
            logger.error("Anthropic API error: %s", exc)
            return f"⚠ AI analysis failed: {exc}"


class OllamaAnalyzer(AnalyzerBase):
    """Local Ollama multimodal analyzer."""

    provider_name = "ollama"
    default_model = "llava"

    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model_name: Optional[str] = None,
    ) -> None:
        super().__init__(model_name=model_name)
        self._endpoint = endpoint.rstrip("/")

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        url = f"{self._endpoint}/api/generate"
        payload = {
            "model": self._model_name,
            "prompt": AI_PROMPT,
            "images": [encoded],
            "stream": False,
        }
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                text = data.get("response", "") or data.get("message", "")
            else:
                text = str(data)
            text = str(text).strip()
            return text or "⚠ AI analysis returned no text."
        except Exception as exc:
            logger.error("Ollama API error: %s", exc)
            return f"⚠ AI analysis failed: {exc}"


class AIAnalyzer(AnalyzerBase):
    """Provider-agnostic analyzer facade."""

    _PROVIDER_MAP = {
        "gemini": GeminiAnalyzer,
        "openai": OpenAIAnalyzer,
        "anthropic": AnthropicAnalyzer,
        "ollama": OllamaAnalyzer,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        env_provider = os.environ.get("AI_PROVIDER")
        resolved_provider = (provider or env_provider or "gemini").lower()
        if resolved_provider not in self._PROVIDER_MAP:
            raise ValueError(
                f"Unsupported AI_PROVIDER '{resolved_provider}'. "
                "Choose from gemini, openai, anthropic, ollama."
            )
        impl_cls = self._PROVIDER_MAP[resolved_provider]
        effective_model = model_name or os.environ.get("AI_MODEL") or None
        self._impl = self._build_impl(
            impl_cls=impl_cls,
            api_key=api_key,
            model_name=effective_model,
        )
        self.provider_name = resolved_provider
        self._model_name = getattr(self._impl, "_model_name", effective_model)

    def _build_impl(
        self,
        impl_cls: Type[AnalyzerBase],
        api_key: Optional[str],
        model_name: Optional[str],
    ) -> AnalyzerBase:
        if impl_cls is OllamaAnalyzer:
            return impl_cls(model_name=model_name)
        return impl_cls(api_key=api_key, model_name=model_name)

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        return self._impl.analyse(image_bytes=image_bytes, mime_type=mime_type)


# ===========================================================================
# FloatingTooltip
# ===========================================================================
class FloatingTooltip(QWidget):
    """Semi-transparent, frameless, always-on-top tooltip overlay.

    The widget is hidden by default.  Call :meth:`show_text` to position and
    reveal it, and :meth:`hide_tooltip` to hide it again.

    Design
    ------
    * Background: dark charcoal with 85 % opacity – readable on any screen
      content without being fully opaque.
    * Rounded corners rendered via QPainterPath clipping for a modern look.
    * The window is never the active window
      (``Qt.WindowType.WindowDoesNotAcceptFocus``) so it never interrupts
      keyboard shortcuts or the active application.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_text: str = ""
        self._setup_window_flags()
        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_window_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keeps it out of the taskbar / Alt-Tab
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # WA_TranslucentBackground allows the window background to be truly
        # transparent so our custom rounded painting shows through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Prevent the window from stealing input focus.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(TOOLTIP_MAX_WIDTH)

        font = QFont("Segoe UI", 10)
        self._label.setFont(font)
        self._label.setStyleSheet("color: #F0F0F0; background: transparent;")

        self._copy_btn = QPushButton("📋 Copy")
        self._copy_btn.setFlat(True)
        self._copy_btn.setStyleSheet(
            "color: #A0A0A0; background: transparent; font-size: 9px;"
            " border: none; text-align: left; padding: 0px;"
        )
        self._copy_btn.clicked.connect(self._copy_to_clipboard)

        layout.addWidget(self._label)
        layout.addWidget(self._copy_btn)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Clipboard helper
    # ------------------------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        """Copy the currently displayed AI response to the system clipboard."""
        QApplication.clipboard().setText(self._current_text)

    # ------------------------------------------------------------------
    # Custom painting – rounded, semi-transparent background
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg_color = QColor(30, 30, 30, 217)  # charcoal, ~85 % opaque
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)

        painter.fillPath(path, bg_color)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_text(self, text: str, cursor_x: int, cursor_y: int) -> None:
        """Display *text* in a tooltip placed near (*cursor_x*, *cursor_y*).

        The tooltip is repositioned so it never overlaps the cursor and never
        goes off-screen.

        Parameters
        ----------
        text:
            The AI-generated explanation to show.
        cursor_x, cursor_y:
            Current cursor position in physical screen pixels.
        """
        self._current_text = text
        self._label.setText(text)
        # Let Qt calculate the natural size before moving.
        self.adjustSize()

        screen: Optional[QScreen] = QApplication.primaryScreen()
        if screen is not None:
            screen_geom = screen.availableGeometry()
            max_x = screen_geom.right() - self.width()
            max_y = screen_geom.bottom() - self.height()
        else:
            max_x = cursor_x + TOOLTIP_OFFSET_X
            max_y = cursor_y + TOOLTIP_OFFSET_Y

        x = min(cursor_x + TOOLTIP_OFFSET_X, max_x)
        y = min(cursor_y + TOOLTIP_OFFSET_Y, max_y)

        self.move(QPoint(x, y))
        self.show()
        self.raise_()

    def hide_tooltip(self) -> None:
        """Hide the tooltip."""
        self.hide()


# ===========================================================================
# SystemTrayIcon
# ===========================================================================
class SystemTrayIcon(QSystemTrayIcon):
    """System-tray presence for HoverMind.

    Provides a right-click context menu with:

    * **Pause / Resume** – toggle whether the hotkey triggers analysis.
    * **Quit HoverMind** – cleanly exit the application.

    Parameters
    ----------
    controller:
        The :class:`MainController` instance whose
        :meth:`~MainController.set_enabled` method is called when the user
        toggles the pause state.
    parent:
        Optional Qt parent object.
    """

    def __init__(
        self,
        controller: "MainController",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(self._create_icon(), parent)
        self._controller = controller
        self._paused: bool = False
        self._setup_menu()
        self.setToolTip("HoverMind – Hold Alt+Shift to analyse")
        self.show()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_icon() -> QIcon:
        """Build a minimal 16×16 icon programmatically (no image file needed)."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 0, 0, 0))  # transparent base
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(100, 149, 237))  # cornflower blue
        painter.setPen(QColor(70, 110, 200))
        painter.drawEllipse(1, 1, 14, 14)
        painter.end()
        return QIcon(pixmap)

    def _setup_menu(self) -> None:
        menu = QMenu()

        self._toggle_action = QAction("Pause HoverMind")
        self._toggle_action.setCheckable(True)
        self._toggle_action.triggered.connect(self._on_toggle)
        menu.addAction(self._toggle_action)

        menu.addSeparator()

        quit_action = QAction("Quit HoverMind")
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_toggle(self, checked: bool) -> None:
        self._paused = checked
        self._controller.set_enabled(not checked)
        self._toggle_action.setText(
            "Resume HoverMind" if checked else "Pause HoverMind"
        )
        self.setToolTip(
            "HoverMind – Paused"
            if checked
            else "HoverMind – Hold Alt+Shift to analyse"
        )


# ===========================================================================
# MainController
# ===========================================================================
class MainController(QObject):
    """Orchestrates hotkey listening, capture, AI analysis and UI updates.

    The pynput listener runs on a background daemon thread.  When the hotkey
    is held and the cursor has moved, the listener posts a Qt signal to the
    main thread (which owns the Qt event loop) to update the tooltip.  This
    keeps all Qt widget manipulation strictly on the GUI thread.

    Parameters
    ----------
    app:
        The running :class:`QApplication` instance.
    api_key:
        Forwarded to :class:`AIAnalyzer`.  If *None*, the environment
        variable is used.
    provider:
        Optional override for the AI provider. Defaults to ``AI_PROVIDER``
        environment variable (``"gemini"`` when unset).
    model_name:
        Optional override for the provider model. Defaults to ``AI_MODEL``
        environment variable when set, otherwise provider-specific default.
    debounce_ms:
        Minimum number of milliseconds between successive AI calls while the
        hotkey is held and the cursor is moving.  Prevents flooding the API.
        Defaults to the ``DEBOUNCE_MS`` environment variable (800 ms if unset).
    """

    # Signal emitted from the background thread to update the tooltip text
    # safely on the GUI thread.
    _update_tooltip = pyqtSignal(str, int, int)
    _hide_tooltip = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        api_key: Optional[str] = None,
        debounce_ms: int = DEBOUNCE_MS,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._debounce_ms = debounce_ms
        self._enabled: bool = True

        self._capture = ScreenCapture()
        self._analyzer = AIAnalyzer(
            api_key=api_key,
            provider=provider,
            model_name=model_name,
        )
        self._tooltip = FloatingTooltip()

        # Hotkey state
        self._pressed: set = set()
        self._hotkey_active: bool = False
        self._last_cursor: tuple[int, int] = (-1, -1)
        self._analysis_lock = threading.Lock()
        self._analysis_running: bool = False

        # Debounce timer (runs on the GUI thread)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._trigger_analysis_debounced)

        # Mouse polling timer (runs on the GUI thread)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)  # poll every 100 ms
        self._poll_timer.timeout.connect(self._poll_cursor)

        # Connect cross-thread signals
        self._update_tooltip.connect(self._tooltip.show_text)
        self._hide_tooltip.connect(self._tooltip.hide_tooltip)

        # pynput listener (daemon thread)
        self._listener = pynput_keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )

        # System tray icon
        self._tray = SystemTrayIcon(controller=self, parent=self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the hotkey listener and the cursor polling timer."""
        logger.info("HoverMind started. Hold Alt+Shift to activate.")
        self._listener.start()
        self._poll_timer.start()

    def stop(self) -> None:
        """Gracefully stop all background activity."""
        self._poll_timer.stop()
        self._debounce_timer.stop()
        self._listener.stop()
        self._tooltip.hide_tooltip()
        logger.info("HoverMind stopped.")

    def set_enabled(self, enabled: bool) -> None:
        """Pause or resume hotkey-triggered analysis.

        Parameters
        ----------
        enabled:
            ``True`` to resume normal operation; ``False`` to pause so that
            holding Alt+Shift no longer triggers any analysis.
        """
        self._enabled = enabled
        if not enabled:
            self._hide_tooltip.emit()
        logger.info("HoverMind %s.", "enabled" if enabled else "paused")

    # ------------------------------------------------------------------
    # Key event handlers (pynput background thread)
    # ------------------------------------------------------------------

    def _on_key_press(self, key: pynput_keyboard.Key) -> None:
        key = _KEY_NORMALIZE.get(key, key)
        self._pressed.add(key)
        was_active = self._hotkey_active
        self._hotkey_active = HOTKEY_KEYS.issubset(self._pressed)
        if self._hotkey_active and not was_active:
            logger.debug("Hotkey activated.")

    def _on_key_release(self, key: pynput_keyboard.Key) -> None:
        key = _KEY_NORMALIZE.get(key, key)
        self._pressed.discard(key)
        if not HOTKEY_KEYS.issubset(self._pressed):
            if self._hotkey_active:
                logger.debug("Hotkey deactivated.")
            self._hotkey_active = False
            self._hide_tooltip.emit()

    # ------------------------------------------------------------------
    # Cursor polling (GUI thread)
    # ------------------------------------------------------------------

    def _poll_cursor(self) -> None:
        """Check the cursor position and (re-)arm the debounce timer."""
        if not self._hotkey_active or not self._enabled:
            return

        # Retrieve cursor in global screen coordinates via Qt
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        x, y = pos.x(), pos.y()

        if (x, y) != self._last_cursor:
            self._last_cursor = (x, y)
            # Re-arm debounce every time the cursor moves.
            self._debounce_timer.start(self._debounce_ms)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _trigger_analysis_debounced(self) -> None:
        """Called on the GUI thread after the debounce period expires."""
        if not self._hotkey_active or not self._enabled:
            return

        x, y = self._last_cursor
        if x < 0 or y < 0:
            return

        # Only run one analysis at a time.
        with self._analysis_lock:
            if self._analysis_running:
                return
            self._analysis_running = True

        # Show the loading indicator immediately so the user sees feedback.
        self._update_tooltip.emit("🔍 Analysing…", x, y)

        threading.Thread(
            target=self._run_analysis,
            args=(x, y),
            daemon=True,
        ).start()

    def _run_analysis(self, x: int, y: int) -> None:
        """Capture + analyse on a worker thread; emit result to GUI thread."""
        try:
            logger.debug("Capturing at (%d, %d)", x, y)
            image_bytes = self._capture.capture_as_bytes(x, y)

            logger.debug("Sending to Gemini …")
            result = self._analyzer.analyse(image_bytes)

            # Emit to the GUI thread so the tooltip is updated safely.
            self._update_tooltip.emit(result, x, y)
        except Exception as exc:
            logger.error("Analysis pipeline error: %s", exc)
            self._update_tooltip.emit(f"⚠ Error: {exc}", x, y)
        finally:
            with self._analysis_lock:
                self._analysis_running = False


# ===========================================================================
# Entry point
# ===========================================================================
def main() -> None:
    """Create the Qt application and run the event loop."""
    _setup_file_logging()

    if sys.platform == "win32":
        # Python 3.8+ embeds a manifest that declares
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, so Windows rejects Qt's
        # own SetProcessDpiAwarenessContext call with ERROR_ACCESS_DENIED.  The
        # DPI behaviour is already correct; suppress the spurious warning.
        os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window.warning=false")

    app = QApplication(sys.argv)
    # Prevent the application from quitting when the tooltip is closed.
    app.setQuitOnLastWindowClosed(False)

    try:
        controller = MainController(app)
    except ValueError as exc:
        logger.critical("Startup error: %s", exc)
        sys.exit(1)

    controller.start()

    exit_code = app.exec()
    controller.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
