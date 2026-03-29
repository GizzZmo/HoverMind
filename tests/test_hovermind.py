"""
Unit tests for HoverMind components.

These tests are designed to run in a headless CI environment (no display,
no Windows API, no real Gemini API key).  All external dependencies are
mocked.
"""

from __future__ import annotations

import io
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Stub out platform-specific / heavy dependencies before importing hovermind
# so the tests can run on Linux / macOS CI runners too.
# ---------------------------------------------------------------------------

def _make_pynput_stub():
    """Return a minimal stub for the pynput.keyboard module."""
    mod = types.ModuleType("pynput")
    kb = types.ModuleType("pynput.keyboard")

    class _Key:
        alt = "alt"
        alt_l = "alt_l"
        alt_r = "alt_r"
        alt_gr = "alt_gr"
        shift = "shift"
        shift_l = "shift_l"
        shift_r = "shift_r"

    class _Listener:
        def __init__(self, on_press=None, on_release=None):
            self.on_press = on_press
            self.on_release = on_release

        def start(self):
            pass

        def stop(self):
            pass

    kb.Key = _Key
    kb.Listener = _Listener
    mod.keyboard = kb
    return mod, kb


def _make_mss_stub():
    """Return a minimal stub for the mss module."""
    mod = types.ModuleType("mss")
    mod.tools = types.ModuleType("mss.tools")

    class _FakeScreenshot:
        size = (500, 500)
        # BGRA data: 500×500 × 4 bytes of zeros
        bgra = b"\x00" * (500 * 500 * 4)

    class _FakeMss:
        monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def grab(self, region):
            ss = _FakeScreenshot()
            ss.size = (region["width"], region["height"])
            ss.bgra = b"\x00" * (region["width"] * region["height"] * 4)
            return ss

    def _mss_factory():
        return _FakeMss()

    mod.mss = _mss_factory
    return mod


def _make_genai_stub():
    """Return a minimal stub for the google.genai module."""
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")

    class _Part:
        @staticmethod
        def from_bytes(data, mime_type):
            obj = _Part()
            obj.data = data
            obj.mime_type = mime_type
            return obj

    class _Response:
        text = "This is a test button in a dialog box."

    class _Models:
        def generate_content(self, model, contents):
            return _Response()

    class _Client:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = _Models()

    types_mod.Part = _Part
    genai_mod.Client = _Client
    genai_mod.types = types_mod
    google_mod.genai = genai_mod

    return google_mod, genai_mod, types_mod


def _make_openai_stub():
    """Return a minimal stub for the openai module."""
    mod = types.ModuleType("openai")

    class _Message:
        def __init__(self):
            self.content = "openai vision response"

    class _Choice:
        def __init__(self):
            self.message = _Message()

    class _ChatCompletions:
        def create(self, *args, **kwargs):
            return types.SimpleNamespace(choices=[_Choice()])

    class _Chat:
        def __init__(self):
            self.completions = _ChatCompletions()

    class OpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = _Chat()

    mod.OpenAI = OpenAI
    return mod


def _make_anthropic_stub():
    """Return a minimal stub for the anthropic module."""
    mod = types.ModuleType("anthropic")

    class _ResponsePart:
        def __init__(self, text):
            self.text = text

    class _Messages:
        def create(self, *args, **kwargs):
            return types.SimpleNamespace(content=[_ResponsePart("anthropic vision response")])

    class Anthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = _Messages()

    mod.Anthropic = Anthropic
    return mod


def _make_requests_stub():
    """Return a minimal stub for the requests module."""
    mod = types.ModuleType("requests")

    class _Response:
        def __init__(self):
            self._json = {"response": "ollama vision response"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._json

        @property
        def status_code(self):
            return 200

    def post(url, **kwargs):
        return _Response()

    mod.post = post
    return mod


def _make_pyqt6_stub():
    """Return a minimal stub for PyQt6 so tests run without a display."""
    pyqt6 = types.ModuleType("PyQt6")
    core = types.ModuleType("PyQt6.QtCore")
    widgets = types.ModuleType("PyQt6.QtWidgets")
    gui = types.ModuleType("PyQt6.QtGui")

    # --- QtCore stubs ---
    class _Qt:
        class WindowType:
            FramelessWindowHint = 0
            WindowStaysOnTopHint = 0
            Tool = 0
            WindowDoesNotAcceptFocus = 0

        class WidgetAttribute:
            WA_TranslucentBackground = 0
            WA_ShowWithoutActivating = 0

        class RenderHint:
            Antialiasing = 0

        class Orientation:
            Horizontal = 0
            Vertical = 1

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _QTimer:
        def __init__(self, *args):
            self._cb = None
            self._single = False
            self.timeout = MagicMock()

        def setSingleShot(self, v):
            self._single = v

        def setInterval(self, ms):
            pass

        def start(self, ms=None):
            pass

        def stop(self):
            pass

        @property
        def is_active(self):
            return False

    class _QPoint:
        def __init__(self, x=0, y=0):
            self.x = x
            self.y = y

    def _pyqtSignal(*args):
        return MagicMock()

    core.Qt = _Qt
    core.QObject = _QObject
    core.QTimer = _QTimer
    core.QPoint = _QPoint
    core.pyqtSignal = _pyqtSignal

    # --- QtWidgets stubs ---
    class _QApplication:
        _instance = None

        def __init__(self, argv):
            _QApplication._instance = self

        @staticmethod
        def primaryScreen():
            screen = MagicMock()
            screen.availableGeometry.return_value = MagicMock(
                right=lambda: 1920,
                bottom=lambda: 1080,
            )
            return screen

        def setQuitOnLastWindowClosed(self, v):
            pass

        @staticmethod
        def clipboard():
            cb = MagicMock()
            cb.setText = MagicMock()
            return cb

        @staticmethod
        def quit():
            pass

        def exec(self):
            return 0

    class _QWidget:
        def __init__(self, *args, **kwargs):
            self._visible = False
            self._pos = (0, 0)

        def setWindowFlags(self, flags):
            pass

        def setAttribute(self, attr, val=True):
            pass

        def setLayout(self, layout):
            pass

        def adjustSize(self):
            pass

        def width(self):
            return 300

        def height(self):
            return 100

        def move(self, point):
            self._pos = (point.x, point.y)

        def show(self):
            self._visible = True

        def raise_(self):
            pass

        def hide(self):
            self._visible = False

    class _QLabel:
        def __init__(self, *args):
            self._text = ""

        def setWordWrap(self, v):
            pass

        def setMaximumWidth(self, w):
            pass

        def setFont(self, f):
            pass

        def setStyleSheet(self, s):
            pass

        def setText(self, t):
            self._text = t

    class _QVBoxLayout:
        def __init__(self, *args):
            pass

        def setContentsMargins(self, *args):
            pass

        def addWidget(self, w):
            pass

        def addLayout(self, layout):
            pass

    class _QFormLayout:
        def __init__(self, *args):
            pass

        def addRow(self, *args):
            pass

    class _QLineEdit:
        def __init__(self, *args):
            self._text = ""

        def setText(self, text):
            self._text = text

        def text(self):
            return self._text

    class _QTextEdit:
        def __init__(self, *args):
            self._text = ""

        def setPlainText(self, text):
            self._text = text

        def toPlainText(self):
            return self._text

    class _QComboBox:
        def __init__(self, *args):
            self._items = []
            self._current = ""
            self._editable = False

        def addItems(self, items):
            self._items.extend(items)
            if items and not self._current:
                self._current = items[0]

        def setEditable(self, editable):
            self._editable = editable

        def setCurrentText(self, text):
            self._current = text

        def currentText(self):
            return self._current

    class _QSlider:
        def __init__(self, *args):
            self._min = 0
            self._max = 100
            self._value = 0

        def setMinimum(self, v):
            self._min = v

        def setMaximum(self, v):
            self._max = v

        def setValue(self, v):
            self._value = v

        def value(self):
            return self._value

    class _QSpinBox:
        def __init__(self, *args):
            self._value = 0
            self._min = 0
            self._max = 0

        def setMinimum(self, v):
            self._min = v

        def setMaximum(self, v):
            self._max = v

        def setValue(self, v):
            self._value = v

        def value(self):
            return self._value

    widgets.QApplication = _QApplication
    widgets.QWidget = _QWidget
    widgets.QLabel = _QLabel
    widgets.QVBoxLayout = _QVBoxLayout
    widgets.QFormLayout = _QFormLayout
    widgets.QLineEdit = _QLineEdit
    widgets.QTextEdit = _QTextEdit
    widgets.QComboBox = _QComboBox
    widgets.QSlider = _QSlider
    widgets.QSpinBox = _QSpinBox

    class _QPushButton:
        def __init__(self, *args):
            self.clicked = MagicMock()

        def setFlat(self, v):
            pass

        def setStyleSheet(self, s):
            pass

    class _QSystemTrayIcon:
        def __init__(self, *args, **kwargs):
            pass

        def setToolTip(self, text):
            pass

        def setContextMenu(self, menu):
            pass

        def show(self):
            pass

        def setIcon(self, icon):
            pass

    class _QMenu:
        def __init__(self, *args):
            pass

        def addAction(self, action_or_text):
            if isinstance(action_or_text, str):
                return _make_action(action_or_text)
            return action_or_text

        def addSeparator(self):
            pass

        def exec(self, *args):
            pass

    def _make_action(text=""):
        action = MagicMock()
        action.triggered = MagicMock()
        action.triggered.connect = MagicMock()
        return action

    widgets.QPushButton = _QPushButton
    widgets.QSystemTrayIcon = _QSystemTrayIcon
    widgets.QMenu = _QMenu

    # --- QtGui stubs ---
    class _QColor:
        def __init__(self, *args):
            pass

    class _QFont:
        def __init__(self, *args):
            pass

    class _QPainter:
        class RenderHint:
            Antialiasing = 0

        def __init__(self, *args):
            pass

        def setRenderHint(self, h):
            pass

        def setBrush(self, b):
            pass

        def setPen(self, p):
            pass

        def drawEllipse(self, *args):
            pass

        def end(self):
            pass

        def fillPath(self, path, color):
            pass

    class _QPainterPath:
        def addRoundedRect(self, *args):
            pass

    class _QScreen:
        pass

    class _QCursor:
        @staticmethod
        def pos():
            p = MagicMock()
            p.x.return_value = 960
            p.y.return_value = 540
            return p

    class _QKeySequence:
        def __init__(self, seq=""):
            self._seq = seq

        def toString(self):
            return self._seq

    class _QKeySequenceEdit:
        def __init__(self, *args):
            self._seq = _QKeySequence()

        def setKeySequence(self, seq):
            self._seq = seq

        def keySequence(self):
            return self._seq

    class _QAction:
        def __init__(self, *args, **kwargs):
            self.triggered = MagicMock()
            self.triggered.connect = MagicMock()
            self._text = args[0] if args else ""
            self._checkable = False
            self._checked = False

        def setCheckable(self, v):
            self._checkable = v

        def setText(self, text):
            self._text = text

        def setChecked(self, v):
            self._checked = v

    class _QIcon:
        def __init__(self, *args):
            pass

    class _QPixmap:
        def __init__(self, *args):
            pass

        def fill(self, color):
            pass

    gui.QColor = _QColor
    gui.QFont = _QFont
    gui.QPainter = _QPainter
    gui.QPainterPath = _QPainterPath
    gui.QScreen = _QScreen
    gui.QCursor = _QCursor
    gui.QAction = _QAction
    gui.QIcon = _QIcon
    gui.QPixmap = _QPixmap
    gui.QKeySequence = _QKeySequence
    gui.QKeySequenceEdit = _QKeySequenceEdit

    pyqt6.QtCore = core
    pyqt6.QtWidgets = widgets
    pyqt6.QtGui = gui
    return pyqt6, core, widgets, gui


# ---------------------------------------------------------------------------
# Register all stubs in sys.modules before importing hovermind
# ---------------------------------------------------------------------------
pynput_mod, pynput_kb = _make_pynput_stub()
sys.modules.setdefault("pynput", pynput_mod)
sys.modules.setdefault("pynput.keyboard", pynput_kb)

mss_mod = _make_mss_stub()
sys.modules.setdefault("mss", mss_mod)
sys.modules.setdefault("mss.tools", mss_mod.tools)

google_mod, genai_mod, genai_types_mod = _make_genai_stub()
sys.modules.setdefault("google", google_mod)
sys.modules.setdefault("google.genai", genai_mod)
sys.modules.setdefault("google.genai.types", genai_types_mod)

openai_mod = _make_openai_stub()
sys.modules.setdefault("openai", openai_mod)

anthropic_mod = _make_anthropic_stub()
sys.modules.setdefault("anthropic", anthropic_mod)

requests_mod = _make_requests_stub()
sys.modules.setdefault("requests", requests_mod)

pyqt6_mod, qt_core, qt_widgets, qt_gui = _make_pyqt6_stub()
sys.modules.setdefault("PyQt6", pyqt6_mod)
sys.modules.setdefault("PyQt6.QtCore", qt_core)
sys.modules.setdefault("PyQt6.QtWidgets", qt_widgets)
sys.modules.setdefault("PyQt6.QtGui", qt_gui)

# dotenv is lightweight but stub it for isolation
dotenv_mod = types.ModuleType("dotenv")
dotenv_mod.load_dotenv = lambda *a, **kw: None
sys.modules.setdefault("dotenv", dotenv_mod)

# Now it is safe to import the application module
import hovermind  # noqa: E402  (must come after stubs are registered)


# ===========================================================================
# Tests
# ===========================================================================

class TestScreenCapture(unittest.TestCase):
    """Tests for the ScreenCapture class."""

    def test_capture_returns_pil_image(self):
        """capture_around should return a PIL Image."""
        from PIL import Image
        sc = hovermind.ScreenCapture()
        img = sc.capture_around(960, 540)
        self.assertIsInstance(img, Image.Image)

    def test_capture_clamps_to_screen_bounds(self):
        """Near-edge coordinates must not cause a negative region size."""
        sc = hovermind.ScreenCapture()
        # Top-left corner — region would normally extend beyond the screen.
        img = sc.capture_around(0, 0)
        w, h = img.size
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_capture_as_bytes_returns_bytes(self):
        """capture_as_bytes must return non-empty bytes."""
        sc = hovermind.ScreenCapture()
        data = sc.capture_as_bytes(960, 540)
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 0)

    def test_capture_as_bytes_is_valid_png(self):
        """capture_as_bytes with default format must produce a valid PNG."""
        from PIL import Image
        sc = hovermind.ScreenCapture()
        data = sc.capture_as_bytes(100, 100)
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "PNG")

    def test_custom_snippet_size(self):
        """ScreenCapture should honour a custom snippet_size."""
        sc = hovermind.ScreenCapture(snippet_size=200)
        img = sc.capture_around(960, 540)
        # The captured image may be smaller if near an edge, but width/height
        # must not exceed the requested snippet size.
        self.assertLessEqual(img.width, 200)
        self.assertLessEqual(img.height, 200)


class TestAIAnalyzer(unittest.TestCase):
    """Tests for the AIAnalyzer class."""

    def test_raises_without_api_key(self):
        """AIAnalyzer must raise ValueError when no API key is available."""
        with patch.dict("os.environ", {}, clear=True):
            # Ensure the env var is not present
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            with self.assertRaises(ValueError):
                hovermind.AIAnalyzer(api_key=None)

    def test_analyse_returns_string(self):
        """analyse() must return a non-empty string."""
        analyzer = hovermind.AIAnalyzer(api_key="fake-key-for-testing")
        result = analyzer.analyse(b"fake-image-data")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_analyse_returns_error_string_on_exception(self):
        """analyse() must return an error string (not raise) on API failure."""
        analyzer = hovermind.AIAnalyzer(
            api_key="fake-key-for-testing",
            provider="gemini",
        )
        # Make the internal client raise an exception
        analyzer._impl._client.models.generate_content = MagicMock(
            side_effect=RuntimeError("network error")
        )
        result = analyzer.analyse(b"fake-image-data")
        self.assertIn("⚠", result)
        self.assertIn("network error", result)

    def test_custom_model_name(self):
        """AIAnalyzer should accept a custom model name."""
        analyzer = hovermind.AIAnalyzer(
            api_key="fake-key", model_name="gemini-1.5-pro"
        )
        self.assertEqual(analyzer._model_name, "gemini-1.5-pro")

    def test_provider_default_is_gemini(self):
        """AIAnalyzer must default to the Gemini provider."""
        with patch.dict("os.environ", {}, clear=True):
            analyzer = hovermind.AIAnalyzer(api_key="fake-key")
        self.assertEqual(analyzer.provider_name, "gemini")

    def test_ai_model_env_override(self):
        """AI_MODEL env var must override the provider default."""
        with patch.dict(
            "os.environ",
            {"GEMINI_API_KEY": "k", "AI_MODEL": "custom-model"},
            clear=True,
        ):
            analyzer = hovermind.AIAnalyzer(api_key=None)
        self.assertEqual(analyzer._model_name, "custom-model")

    def test_openai_provider_selection(self):
        """AI_PROVIDER=openai must select the OpenAI analyzer."""
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "ok", "AI_PROVIDER": "openai"},
            clear=True,
        ):
            analyzer = hovermind.AIAnalyzer(api_key=None)
        self.assertEqual(analyzer.provider_name, "openai")
        self.assertEqual(analyzer._impl.__class__.__name__, "OpenAIAnalyzer")

    def test_invalid_provider_raises(self):
        """Unsupported providers must raise ValueError."""
        with patch.dict(
            "os.environ",
            {"AI_PROVIDER": "unknown", "GEMINI_API_KEY": "k"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                hovermind.AIAnalyzer(api_key=None)

    def test_ollama_requires_no_key(self):
        """Ollama provider should not require an API key."""
        analyzer = hovermind.AIAnalyzer(provider="ollama")
        self.assertEqual(analyzer.provider_name, "ollama")


class TestFloatingTooltip(unittest.TestCase):
    """Tests for the FloatingTooltip widget."""

    def setUp(self):
        self._tooltip = hovermind.FloatingTooltip()

    def test_initially_hidden(self):
        """The tooltip must be hidden when first created."""
        self.assertFalse(self._tooltip._visible)

    def test_show_text_makes_visible(self):
        """show_text must make the tooltip visible."""
        self._tooltip.show_text("Hello World", 500, 300)
        self.assertTrue(self._tooltip._visible)

    def test_hide_tooltip(self):
        """hide_tooltip must hide the tooltip."""
        self._tooltip.show_text("Visible", 100, 100)
        self._tooltip.hide_tooltip()
        self.assertFalse(self._tooltip._visible)

    def test_label_text_is_set(self):
        """show_text must update the internal label text."""
        msg = "This is a PyQt6 button."
        self._tooltip.show_text(msg, 800, 400)
        self.assertEqual(self._tooltip._label._text, msg)


class TestMainController(unittest.TestCase):
    """Tests for the MainController class."""

    def _make_controller(self):
        app = qt_widgets.QApplication([])
        return hovermind.MainController(app, api_key="fake-key")

    def test_instantiation(self):
        """MainController must instantiate without errors."""
        ctrl = self._make_controller()
        self.assertIsNotNone(ctrl)

    def test_hotkey_activation(self):
        """Pressing both hotkey keys must activate the hotkey flag."""
        ctrl = self._make_controller()
        # Simulate pressing Alt then Shift
        ctrl._on_key_press(pynput_kb.Key.alt)
        self.assertFalse(ctrl._hotkey_active)  # only one key so far
        ctrl._on_key_press(pynput_kb.Key.shift)
        self.assertTrue(ctrl._hotkey_active)

    def test_hotkey_deactivation_on_release(self):
        """Releasing a hotkey key must deactivate the flag."""
        ctrl = self._make_controller()
        ctrl._on_key_press(pynput_kb.Key.alt)
        ctrl._on_key_press(pynput_kb.Key.shift)
        self.assertTrue(ctrl._hotkey_active)
        ctrl._on_key_release(pynput_kb.Key.shift)
        self.assertFalse(ctrl._hotkey_active)

    def test_hotkey_activation_with_left_variants(self):
        """Pressing alt_l + shift_l (the actual events sent by pynput) must activate."""
        ctrl = self._make_controller()
        ctrl._on_key_press(pynput_kb.Key.alt_l)
        self.assertFalse(ctrl._hotkey_active)
        ctrl._on_key_press(pynput_kb.Key.shift_l)
        self.assertTrue(ctrl._hotkey_active)

    def test_hotkey_activation_with_right_variants(self):
        """Pressing alt_r + shift_r must also activate the hotkey."""
        ctrl = self._make_controller()
        ctrl._on_key_press(pynput_kb.Key.alt_r)
        ctrl._on_key_press(pynput_kb.Key.shift_r)
        self.assertTrue(ctrl._hotkey_active)

    def test_hotkey_deactivation_with_left_variants(self):
        """Releasing shift_l must deactivate the hotkey."""
        ctrl = self._make_controller()
        ctrl._on_key_press(pynput_kb.Key.alt_l)
        ctrl._on_key_press(pynput_kb.Key.shift_l)
        self.assertTrue(ctrl._hotkey_active)
        ctrl._on_key_release(pynput_kb.Key.shift_l)
        self.assertFalse(ctrl._hotkey_active)

    def test_hotkey_alt_gr_variant(self):
        """alt_gr should also be treated as alt for the hotkey."""
        ctrl = self._make_controller()
        ctrl._on_key_press(pynput_kb.Key.alt_gr)
        ctrl._on_key_press(pynput_kb.Key.shift_l)
        self.assertTrue(ctrl._hotkey_active)

    def test_stop_does_not_raise(self):
        """stop() must not raise any exceptions."""
        ctrl = self._make_controller()
        ctrl.start()
        ctrl.stop()


class TestDebounceConfig(unittest.TestCase):
    """Tests for configurable debounce delay (roadmap 2.5)."""

    def test_default_debounce_is_module_constant(self):
        """MainController default debounce must equal the DEBOUNCE_MS constant."""
        import inspect
        sig = inspect.signature(hovermind.MainController.__init__)
        default = sig.parameters["debounce_ms"].default
        self.assertEqual(default, hovermind.DEBOUNCE_MS)

    def test_debounce_ms_constant_type(self):
        """DEBOUNCE_MS must be an integer."""
        self.assertIsInstance(hovermind.DEBOUNCE_MS, int)

    def test_custom_debounce_stored(self):
        """A custom debounce_ms value must be stored on the controller."""
        app = qt_widgets.QApplication([])
        ctrl = hovermind.MainController(app, api_key="fake-key", debounce_ms=1200)
        self.assertEqual(ctrl._debounce_ms, 1200)


class TestFileLogging(unittest.TestCase):
    """Tests for optional file logging (roadmap 2.6)."""

    def test_no_file_handler_when_env_unset(self):
        """No FileHandler should be added when HOVERMIND_LOG_FILE is empty."""
        import logging as _logging
        root = _logging.getLogger()
        file_handlers_before = [
            h for h in root.handlers if isinstance(h, _logging.FileHandler)
        ]
        count_before = len(file_handlers_before)
        with patch.object(hovermind, "HOVERMIND_LOG_FILE", ""):
            hovermind._setup_file_logging()
        file_handlers_after = [
            h for h in root.handlers if isinstance(h, _logging.FileHandler)
        ]
        self.assertEqual(len(file_handlers_after), count_before)

    def test_file_handler_added(self):
        """_setup_file_logging() must add a FileHandler when path is non-empty."""
        import logging as _logging
        import tempfile, os as _os
        root = _logging.getLogger()
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tf:
            log_path = tf.name
        try:
            with patch.object(hovermind, "HOVERMIND_LOG_FILE", log_path):
                hovermind._setup_file_logging()
            file_handlers = [
                h for h in root.handlers if isinstance(h, _logging.FileHandler)
            ]
            paths = [h.baseFilename for h in file_handlers]
            self.assertIn(_os.path.abspath(log_path), [_os.path.abspath(p) for p in paths])
        finally:
            # Remove the added handler to avoid polluting other tests
            for h in list(root.handlers):
                if isinstance(h, _logging.FileHandler) and h.baseFilename == _os.path.abspath(log_path):
                    root.removeHandler(h)
                    h.close()
            _os.unlink(log_path)


class TestLoadingIndicator(unittest.TestCase):
    """Tests for the "Loading…" indicator (roadmap 2.4)."""

    def test_loading_text_shown_before_analysis(self):
        """Triggering debounced analysis must show the loading text in the tooltip."""
        app = qt_widgets.QApplication([])
        ctrl = hovermind.MainController(app, api_key="fake-key")
        ctrl._hotkey_active = True
        ctrl._enabled = True
        ctrl._last_cursor = (100, 200)

        emitted = []
        ctrl._update_tooltip.emit = lambda text, x, y: emitted.append(text)

        # Prevent the background thread from actually running
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            ctrl._trigger_analysis_debounced()

        self.assertTrue(any("nalys" in t for t in emitted),
                        f"Expected loading text in emitted signals, got: {emitted}")


class TestSetEnabled(unittest.TestCase):
    """Tests for MainController.set_enabled (roadmap 2.1)."""

    def _make_controller(self):
        app = qt_widgets.QApplication([])
        return hovermind.MainController(app, api_key="fake-key")

    def test_initially_enabled(self):
        """Controller must start in the enabled state."""
        ctrl = self._make_controller()
        self.assertTrue(ctrl._enabled)

    def test_set_enabled_false(self):
        """set_enabled(False) must clear the enabled flag."""
        ctrl = self._make_controller()
        ctrl.set_enabled(False)
        self.assertFalse(ctrl._enabled)

    def test_set_enabled_true(self):
        """set_enabled(True) must restore the enabled flag."""
        ctrl = self._make_controller()
        ctrl.set_enabled(False)
        ctrl.set_enabled(True)
        self.assertTrue(ctrl._enabled)

    def test_poll_cursor_respects_enabled(self):
        """_poll_cursor must do nothing when _enabled is False."""
        ctrl = self._make_controller()
        ctrl._hotkey_active = True
        ctrl._enabled = False
        initial_cursor = ctrl._last_cursor
        ctrl._poll_cursor()
        # Debounce timer should not have been started (cursor unchanged)
        self.assertEqual(ctrl._last_cursor, initial_cursor)


class TestSystemTrayIcon(unittest.TestCase):
    """Tests for the SystemTrayIcon class (roadmap 2.1)."""

    def _make_controller(self):
        app = qt_widgets.QApplication([])
        return hovermind.MainController(app, api_key="fake-key")

    def test_controller_has_tray(self):
        """MainController must expose a _tray attribute after construction."""
        ctrl = self._make_controller()
        self.assertTrue(hasattr(ctrl, "_tray"))
        self.assertIsNotNone(ctrl._tray)

    def test_tray_is_system_tray_icon(self):
        """_tray must be an instance of SystemTrayIcon."""
        ctrl = self._make_controller()
        self.assertIsInstance(ctrl._tray, hovermind.SystemTrayIcon)

    def test_tray_on_toggle_pause(self):
        """_on_toggle(True) must disable the controller."""
        ctrl = self._make_controller()
        ctrl._tray._on_toggle(True)
        self.assertFalse(ctrl._enabled)

    def test_tray_on_toggle_resume(self):
        """_on_toggle(False) must re-enable the controller."""
        ctrl = self._make_controller()
        ctrl._tray._on_toggle(True)   # pause
        ctrl._tray._on_toggle(False)  # resume
        self.assertTrue(ctrl._enabled)


class TestFloatingTooltipCopy(unittest.TestCase):
    """Tests for the clipboard copy button (roadmap 2.3)."""

    def setUp(self):
        self._tooltip = hovermind.FloatingTooltip()

    def test_copy_button_exists(self):
        """FloatingTooltip must have a _copy_btn attribute."""
        self.assertTrue(hasattr(self._tooltip, "_copy_btn"))

    def test_current_text_updated_on_show(self):
        """show_text must update _current_text."""
        self._tooltip.show_text("Hello World", 100, 100)
        self.assertEqual(self._tooltip._current_text, "Hello World")

    def test_copy_to_clipboard_does_not_raise(self):
        """_copy_to_clipboard must not raise even when text is empty."""
        self._tooltip._copy_to_clipboard()  # should be silent

    def test_copy_to_clipboard_after_show(self):
        """_copy_to_clipboard must not raise after show_text has been called."""
        self._tooltip.show_text("AI response text", 500, 300)
        self._tooltip._copy_to_clipboard()  # should be silent


class TestAppSettings(unittest.TestCase):
    """Tests for settings normalisation and clamping (roadmap 4.x)."""

    def test_hotkey_normalises_tokens(self):
        settings = hovermind.AppSettings(hotkey="Ctrl+Alt")
        self.assertEqual(settings.hotkey, ["ctrl", "alt"])

    def test_snippet_size_is_clamped(self):
        settings = hovermind.AppSettings(snippet_size=10)
        self.assertEqual(settings.snippet_size, hovermind.SNIPPET_MIN)


class TestConfigManager(unittest.TestCase):
    """Ensure config round-trips to disk."""

    def test_save_and_load_round_trip(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            cfg = hovermind.ConfigManager(path=cfg_path)
            settings = hovermind.AppSettings(
                hotkey=["ctrl", "h"],
                snippet_size=260,
                ai_prompt="Always reply in tests",
                theme="light",
                font_size=12,
                response_language="French",
            )
            cfg.save(settings)
            loaded = cfg.load()

        self.assertEqual(loaded.hotkey, ["ctrl", "h"])
        self.assertEqual(loaded.snippet_size, 260)
        self.assertEqual(loaded.response_language, "French")
        self.assertEqual(loaded.ai_prompt, "Always reply in tests")


class TestPromptBuilder(unittest.TestCase):
    """Tests for prompt construction with language preference."""

    def test_appends_language_when_provided(self):
        prompt = hovermind.build_prompt("Explain", "Spanish")
        self.assertIn("Spanish", prompt)

    def test_auto_language_keeps_prompt(self):
        prompt = hovermind.build_prompt("Explain", "auto")
        self.assertEqual(prompt, "Explain")


class TestCustomHotkeyController(unittest.TestCase):
    """Controller must respect settings from the config manager."""

    def test_controller_uses_custom_hotkey_and_snippet(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            cfg = hovermind.ConfigManager(path=cfg_path)
            custom_settings = hovermind.AppSettings(
                hotkey=["ctrl", "h"],
                snippet_size=220,
                ai_prompt="Custom",
                theme="dark",
                font_size=11,
                response_language="German",
            )
            cfg.save(custom_settings)
            app = qt_widgets.QApplication([])
            with patch.object(hovermind, "ConfigManager", return_value=cfg):
                ctrl = hovermind.MainController(app, api_key="fake-key")

        self.assertEqual(ctrl._hotkey_keys, frozenset(["ctrl", "h"]))
        self.assertEqual(ctrl._capture._snippet_size, 220)
        self.assertIn("German", ctrl._analyzer._prompt)


if __name__ == "__main__":
    unittest.main()
