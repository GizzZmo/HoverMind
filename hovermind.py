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
* DPI Awareness: On high-DPI displays Windows scales logical pixels differently
  from physical pixels.  PyQt6 calls SetProcessDpiAwarenessContext at startup
  (DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2), so every coordinate we receive
  is in physical pixels and every mss capture matches them exactly.
* Always-on-top: Qt.WindowType.WindowStaysOnTopHint combined with
  Qt.WindowType.Tool prevents the tooltip from stealing focus or appearing in
  the taskbar.
* mss is used for capture because it talks directly to the Win32 GDI API,
  making it 3-10× faster than PIL.ImageGrab on Windows.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Third-party imports
# ---------------------------------------------------------------------------
import mss
import mss.tools
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from pynput import keyboard as pynput_keyboard
from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QScreen
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

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
AI_PROMPT: str = (
    "Briefly explain what the user is pointing at in the center of this "
    "image. If it's code, explain it. If it's an image, describe it. If "
    "it's a UI element, state its function. Keep it under 3 sentences."
)


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
# AIAnalyzer
# ===========================================================================
class AIAnalyzer:
    """Sends a screen snippet to the Google Gemini Vision API.

    The Gemini model receives the image together with a short system prompt
    asking for a concise explanation of what is visible in the centre.

    Parameters
    ----------
    api_key:
        Gemini API key.  If *None* the value is read from the ``GEMINI_API_KEY``
        environment variable (populated via .env by python-dotenv).
    model_name:
        Gemini model identifier.  Defaults to ``"gemini-1.5-flash"`` which
        offers a good balance between speed and vision quality.
    """

    _DEFAULT_MODEL = "gemini-1.5-flash"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = _DEFAULT_MODEL,
    ) -> None:
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or pass it explicitly."
            )
        self._client = genai.Client(api_key=resolved_key)
        self._model_name = model_name

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def analyse(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Ask the model to explain what is shown in *image_bytes*.

        Parameters
        ----------
        image_bytes:
            Raw encoded image data (PNG or JPEG).
        mime_type:
            MIME type of *image_bytes*.  Must match the actual encoding.

        Returns
        -------
        str
            The model's textual response, stripped of leading/trailing
            whitespace.  Returns a user-visible error string on failure so
            the UI always has something meaningful to display.
        """
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

        layout.addWidget(self._label)
        self.setLayout(layout)

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
    debounce_ms:
        Minimum number of milliseconds between successive AI calls while the
        hotkey is held and the cursor is moving.  Prevents flooding the API.
    """

    # Signal emitted from the background thread to update the tooltip text
    # safely on the GUI thread.
    _update_tooltip = pyqtSignal(str, int, int)
    _hide_tooltip = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        api_key: Optional[str] = None,
        debounce_ms: int = 800,
    ) -> None:
        super().__init__()
        self._app = app
        self._debounce_ms = debounce_ms

        self._capture = ScreenCapture()
        self._analyzer = AIAnalyzer(api_key=api_key)
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

    # ------------------------------------------------------------------
    # Key event handlers (pynput background thread)
    # ------------------------------------------------------------------

    def _on_key_press(self, key: pynput_keyboard.Key) -> None:
        self._pressed.add(key)
        was_active = self._hotkey_active
        self._hotkey_active = HOTKEY_KEYS.issubset(self._pressed)
        if self._hotkey_active and not was_active:
            logger.debug("Hotkey activated.")

    def _on_key_release(self, key: pynput_keyboard.Key) -> None:
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
        if not self._hotkey_active:
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
        if not self._hotkey_active:
            return

        x, y = self._last_cursor
        if x < 0 or y < 0:
            return

        # Only run one analysis at a time.
        with self._analysis_lock:
            if self._analysis_running:
                return
            self._analysis_running = True

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
