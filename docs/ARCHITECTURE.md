# HoverMind — Architecture Guide

This document provides a detailed description of HoverMind's internal design, data flow, threading model, and Windows-specific considerations.

---

## Overview

HoverMind is a single-file Python application (`hovermind.py`) composed of four classes, each with a clearly bounded responsibility:

```
hovermind.py
├── ScreenCapture       — screenshot acquisition
├── AIAnalyzer          — Gemini Vision API client
├── FloatingTooltip     — PyQt6 overlay widget
└── MainController      — orchestration + lifecycle
```

The application runs exactly two threads:

| Thread | Owner | Responsibilities |
|--------|-------|-----------------|
| **GUI thread** | Qt event loop (`app.exec()`) | Owns all Qt widgets; runs `QTimer` callbacks; receives cross-thread signals |
| **Listener thread** | `pynput.keyboard.Listener` (daemon) | Monitors keyboard events; updates `_hotkey_active` flag; triggers the debounce timer via `QTimer.start()` on the GUI thread |

Worker threads (one per analysis) are spawned as needed and are also daemon threads so they do not block application shutdown.

---

## Startup Sequence

```
main()
  │
  ├─ QApplication(sys.argv)
  │    └─ setQuitOnLastWindowClosed(False)   ← keep alive when tooltip closes
  │
  ├─ MainController(app)
  │    ├─ ScreenCapture()
  │    ├─ AIAnalyzer(api_key)               ← raises ValueError if no key
  │    ├─ FloatingTooltip()                 ← hidden QWidget
  │    ├─ QTimer (debounce, single-shot)
  │    ├─ QTimer (poll, 100 ms interval)
  │    └─ pynput Listener (not yet started)
  │
  ├─ controller.start()
  │    ├─ listener.start()                  ← spawns daemon thread
  │    └─ poll_timer.start()               ← GUI thread, every 100 ms
  │
  └─ app.exec()                             ← blocks; runs Qt event loop
```

---

## Data Flow

```
[User holds Alt+Shift]
       │
       ▼
pynput Listener thread
  _on_key_press() → _hotkey_active = True
       │
       ▼ (every 100 ms on GUI thread)
_poll_cursor()
  QCursor.pos() → (x, y)
  cursor moved? → debounce_timer.start(800)
       │
       ▼ (after 800 ms of cursor stillness)
_trigger_analysis_debounced()   [GUI thread]
  hotkey still active? → spawn Worker Thread
       │
       ▼
_run_analysis(x, y)   [worker thread]
  ScreenCapture.capture_as_bytes(x, y)   → PNG bytes
  AIAnalyzer.analyse(png_bytes)          → text
  _update_tooltip.emit(text, x, y)       → Qt signal
       │
       ▼ (marshalled to GUI thread)
FloatingTooltip.show_text(text, x, y)
  label.setText(text)
  adjustSize()
  clamp to screen bounds
  move(x + 20, y + 20)
  show() + raise_()
       │
[User releases Alt or Shift]
       │
pynput Listener thread
  _on_key_release() → _hotkey_active = False
  _hide_tooltip.emit()                   → Qt signal
       │
       ▼ (GUI thread)
FloatingTooltip.hide_tooltip()
```

---

## Class Reference

### `ScreenCapture`

**Purpose:** Grab a square pixel region centred on the cursor.

**Key parameters:**
- `snippet_size` (default `500`) — side length in physical pixels.

**How it works:**
1. Computes a bounding box `[x - half, y - half, x + half, y + half]`.
2. Clamps each edge to `mss.monitors[0]` (the virtual all-monitor bounding box) to avoid off-screen captures.
3. Uses `mss.mss().grab(region)` which calls `BitBlt` via Win32 GDI — significantly faster than `PIL.ImageGrab`.
4. The raw screenshot is in BGRA format; it is converted to RGB with `Image.frombytes("RGB", size, bgra, "raw", "BGRX")`.
5. `capture_as_bytes()` encodes the PIL Image to PNG (or JPEG) and returns bytes suitable for API transmission.

**Why `mss` instead of `PIL.ImageGrab`?**
`mss` talks directly to the Windows GDI API and is 3–10× faster for small regions. It also handles multi-monitor setups more predictably.

---

### `AIAnalyzer`

**Purpose:** Send a screenshot to the Google Gemini Vision API and return a human-readable explanation.

**Key parameters:**
- `api_key` — resolved from the constructor argument, then `GEMINI_API_KEY` env var. Raises `ValueError` if neither is set.
- `model_name` — defaults to `"gemini-1.5-flash"` (good speed/quality trade-off for vision tasks).

**How it works:**
1. Constructs a `google.genai.Client` with the provided key.
2. Wraps the raw PNG bytes in a `genai_types.Part.from_bytes(data, mime_type="image/png")` object.
3. Calls `client.models.generate_content(model, [image_part, AI_PROMPT])`.
4. Returns `response.text.strip()`.
5. Any exception is caught, logged, and returned as a `"⚠ AI analysis failed: …"` string so the UI always has something to display.

**`AI_PROMPT` constant:**
```python
"Briefly explain what the user is pointing at in the center of this image. "
"If it's code, explain it. If it's an image, describe it. If it's a UI "
"element, state its function. Keep it under 3 sentences."
```
This prompt keeps responses concise and actionable. It can be customised at the top of `hovermind.py`.

---

### `FloatingTooltip`

**Purpose:** Display the AI explanation near the cursor without disrupting the active window.

**Window flags used:**

| Flag | Effect |
|------|--------|
| `FramelessWindowHint` | No title bar, no border |
| `WindowStaysOnTopHint` | Always drawn above other windows |
| `Tool` | Hidden from taskbar and Alt-Tab switcher |
| `WindowDoesNotAcceptFocus` | Never steals keyboard focus |

**Widget attributes:**

| Attribute | Effect |
|-----------|--------|
| `WA_TranslucentBackground` | Alpha channel respected — allows rounded corners to show through |
| `WA_ShowWithoutActivating` | Tooltip becomes visible without activating (changing focused window) |

**Custom painting:**
`paintEvent` draws a dark charcoal rounded rectangle (`QColor(30, 30, 30, 217)` — ~85% opaque) using `QPainterPath.addRoundedRect` and `QPainter.fillPath`. The 10 px corner radius gives the tooltip a modern appearance.

**Screen-edge clamping in `show_text`:**
```
x = min(cursor_x + OFFSET_X, screen.right()  - tooltip.width())
y = min(cursor_y + OFFSET_Y, screen.bottom() - tooltip.height())
```
This prevents the tooltip from overflowing off the right or bottom edge of the primary screen.

---

### `MainController`

**Purpose:** Orchestrate all components and manage the application lifecycle.

**Threading model:**
- `pynput.keyboard.Listener` runs on its own daemon thread. Key press/release handlers (`_on_key_press`, `_on_key_release`) update `_hotkey_active` and call `_hide_tooltip.emit()`. These are the *only* cross-thread operations — they use Qt's signal/slot mechanism which is thread-safe.
- `_poll_cursor` runs on the GUI thread (via `QTimer`) every 100 ms. It reads `QCursor.pos()` and, if the cursor has moved while the hotkey is active, restarts the debounce timer.
- `_trigger_analysis_debounced` runs on the GUI thread after the debounce period expires. It spawns a single daemon worker thread for the capture + analyse pipeline.
- `_run_analysis` runs on the worker thread. It captures the screen, calls the AI, and emits `_update_tooltip` to pass the result back to the GUI thread.

**Concurrency lock (`_analysis_lock`):**
A `threading.Lock` guards `_analysis_running`. If a previous analysis is still in flight when the debounce fires again, the new request is dropped rather than allowing parallel API calls. This prevents response ordering issues and excessive API usage.

**Signals:**

| Signal | Direction | Purpose |
|--------|-----------|---------|
| `_update_tooltip(str, int, int)` | worker → GUI | Show the AI result in the tooltip |
| `_hide_tooltip()` | listener → GUI | Hide the tooltip when the hotkey is released |

---

## Windows-Specific Details

### DPI Awareness

```python
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
```

This call is made at module import time (before any Win32 window is created). Without it, Windows scales logical coordinates differently from physical pixels on high-DPI monitors, causing the captured region to be offset from the visible cursor position.

### Why `mss` for screenshots?

`mss` uses `BitBlt` (Win32 GDI) under the hood, which captures the composited screen including hardware-accelerated content (games, video, browsers with hardware acceleration). `PIL.ImageGrab` on Windows uses a different path that is slower and can miss some composited layers.

### Always-on-top and focus avoidance

Combining `WindowStaysOnTopHint` with `Tool` and `WindowDoesNotAcceptFocus` achieves the desired overlay behaviour: the tooltip appears above all other windows, is not listed in Alt-Tab or the taskbar, and never moves keyboard focus away from the user's active application.

---

## Dependency Summary

| Library | Version | Role |
|---------|---------|------|
| `PyQt6` | ≥6.6.0 | GUI framework (overlay window, event loop, timers, signals) |
| `mss` | ≥9.0.1 | Fast Win32 GDI screenshot capture |
| `Pillow` | ≥10.0.0 | BGRA→RGB conversion, PNG encoding |
| `google-genai` | ≥1.0.0 | Google Gemini Vision API client |
| `pynput` | ≥1.7.7 | Global keyboard listener (daemon thread) |
| `python-dotenv` | ≥1.0.0 | Load `GEMINI_API_KEY` from `.env` file |
