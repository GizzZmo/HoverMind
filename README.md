# 🖱️ HoverMind

<p align="center">
  <b>AI-powered context lens for your Windows desktop</b><br/>
  Hold <kbd>Alt</kbd>+<kbd>Shift</kbd> and hover over anything on screen to get an instant AI explanation.
</p>

<p align="center">
  <a href="https://github.com/GizzZmo/HoverMind/actions"><img alt="CI" src="https://github.com/GizzZmo/HoverMind/actions/workflows/ci.yml/badge.svg"/></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue.svg"/></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-green.svg"/></a>
  <img alt="Platform: Windows" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey.svg"/>
</p>

---

HoverMind turns your mouse pointer into a context-aware AI assistant. Hold **Alt + Shift**, hover over anything on screen, and a frosted-glass tooltip appears with a concise AI-generated explanation — code, UI elements, foreign text, diagrams, photos, error messages and more.

## Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Getting Started](#-getting-started)
- [Configuration Reference](#-configuration-reference)
- [Usage](#-usage)
- [Development](#-development)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **Multi-provider AI** | Plug in Google Gemini (default), OpenAI GPT-4o Vision, Anthropic Claude Vision, or local Ollama models via `AI_PROVIDER` / `AI_MODEL` |
| **Universal vision** | Explain code snippets, UI icons, error messages, foreign-language text, diagrams, photos — anything visible on screen |
| **Unobtrusive overlay** | Frameless, semi-transparent, always-on-top tooltip that never steals focus or appears in Alt-Tab |
| **DPI-aware capture** | Calls `SetProcessDpiAwareness(2)` at startup so coordinates are always physical pixels on any monitor scaling |
| **Debounced analysis** | Waits for the cursor to settle (800 ms by default) before firing an API request — no API flooding |
| **Thread-safe UI** | Capture and AI calls run on daemon worker threads; Qt signals safely marshal results back to the GUI thread |
| **Graceful error handling** | API failures surface as a readable ⚠ message in the tooltip instead of crashing |
| **Cross-environment tests** | Full unit test suite with mocked dependencies that runs on Linux/macOS CI runners |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   MainController                     │
│  (QObject – owns the Qt event loop thread)           │
│                                                      │
│  ┌─────────────┐   key events      ┌──────────────┐  │
│  │  pynput     │ ────────────────▶ │ Debounce     │  │
│  │  Listener   │   (daemon thread) │ QTimer       │  │
│  └─────────────┘                  └──────┬───────┘  │
│                                          │ fires     │
│                                   ┌──────▼───────┐  │
│                                   │ Worker Thread│  │
│                                   │  ┌──────────┐│  │
│                                   │  │ Screen-  ││  │
│                                   │  │ Capture  ││  │
│                                   │  └────┬─────┘│  │
│                                   │       │ PNG  │  │
│                                   │  ┌────▼─────┐│  │
│                                   │  │AIAnalyzer││  │
│                                   │  │ (provider││  │
│                                   │  │  plug-in)││  │
│                                   │  └────┬─────┘│  │
│                                   └───────┼──────┘  │
│                       Qt signal (text)    │          │
│                                   ┌───────▼──────┐  │
│                                   │FloatingTooltip│  │
│                                   │  (QWidget)   │  │
│                                   └──────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Components

| Class | File | Responsibility |
|-------|------|----------------|
| `ScreenCapture` | `hovermind.py` | Grabs a 500×500 px region around the cursor using `mss` (direct Win32 GDI), clamps to screen bounds, converts BGRA→RGB via Pillow |
| `AIAnalyzer` | `hovermind.py` | Provider-agnostic facade that selects Gemini / OpenAI / Anthropic / Ollama based on `AI_PROVIDER` / `AI_MODEL`; returns a plain-text explanation |
| `FloatingTooltip` | `hovermind.py` | PyQt6 frameless widget with custom rounded semi-transparent painting, word-wrapped label, and screen-edge clamping |
| `MainController` | `hovermind.py` | Ties pynput listener → debounce timer → worker thread → Qt signal → tooltip; manages application lifecycle |

For a deeper dive see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 🚀 Getting Started

### Prerequisites

- **Windows 10 or 11** (Linux/macOS supported for development and CI)
- **Python 3.11 or newer**
- At least one AI credential:
  - **Google Gemini API key** — obtain at [Google AI Studio](https://aistudio.google.com/app/apikey)
  - **OpenAI API key** — from [platform.openai.com](https://platform.openai.com/)
  - **Anthropic API key** — from [console.anthropic.com](https://console.anthropic.com/)
  - Or a **local Ollama** instance with a multimodal model (e.g. `ollama pull llava`)

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/GizzZmo/HoverMind.git
   cd HoverMind
   ```

2. Create and activate a virtual environment (recommended):

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux (for development only)
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure your AI provider:

   ```bash
   copy .env.example .env      # Windows
   # cp .env.example .env      # macOS / Linux
   ```

   Open `.env` and set your provider (defaults to Gemini):

   ```
   AI_PROVIDER=gemini          # or openai | anthropic | ollama
   GEMINI_API_KEY=AIza...      # required for Gemini
   OPENAI_API_KEY=...          # required for OpenAI
   ANTHROPIC_API_KEY=...       # required for Anthropic
   # AI_MODEL=gpt-4o-mini      # optional override per provider
   ```

---

## ⚙️ Configuration Reference

All runtime behaviour can be tuned via the module-level constants in `hovermind.py` or overridden with environment variables.

| Constant | Default | Description |
|----------|---------|-------------|
| `SNIPPET_SIZE` | `500` | Width and height (px) of the screen region captured around the cursor |
| `TOOLTIP_MAX_WIDTH` | `420` | Maximum pixel width of the tooltip widget before text wraps |
| `TOOLTIP_OFFSET_X` | `20` | Horizontal gap between the cursor tip and the left edge of the tooltip |
| `TOOLTIP_OFFSET_Y` | `20` | Vertical gap between the cursor tip and the top edge of the tooltip |
| `HOTKEY_KEYS` | `{Alt, Shift}` | Set of keys that must all be held to activate HoverMind |
| `AI_PROMPT` | *(see source)* | System prompt sent to the active provider along with every screenshot |

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_PROVIDER` | No (default `gemini`) | `gemini` \| `openai` \| `anthropic` \| `ollama` |
| `AI_MODEL` | No | Override the provider's default model |
| `GEMINI_API_KEY` | Yes (for Gemini) | Google Gemini API key. Also accepted as a constructor argument. |
| `OPENAI_API_KEY` | Yes (for OpenAI) | OpenAI API key |
| `ANTHROPIC_API_KEY` | Yes (for Anthropic) | Anthropic API key |
| `DEBOUNCE_MS` | No | Debounce delay in milliseconds between analyses |
| `HOVERMIND_LOG_FILE` | No | Optional log file path |

---

## 🖱️ Usage

1. Start HoverMind:

   ```bash
   python hovermind.py
   ```

   You should see:

   ```
   2024-01-15 12:00:00,000 [INFO] hovermind: HoverMind started. Hold Alt+Shift to activate.
   ```

2. **Hold Alt + Shift** and move your cursor over anything on screen.

3. After the cursor settles for ~800 ms, a tooltip appears near your cursor with an AI-generated explanation.

4. **Release** either key to dismiss the tooltip.

5. Press **Ctrl + C** in the terminal (or close it) to quit.

### What can HoverMind explain?

- **Code**: functions, class definitions, algorithms, error stack traces
- **UI elements**: buttons, icons, menu items, dialog boxes
- **Images**: photos, screenshots, charts, diagrams
- **Text**: foreign languages (auto-translated), abbreviations, technical jargon
- **Error messages**: system alerts, compiler output, log entries

---

## 🛠️ Development

### Running the tests

The test suite is designed to run headlessly on any OS (no display, no Windows API, no real API key required):

```bash
pip install -r requirements.txt
python -m unittest tests/test_hovermind.py # run the main suite
# or run all tests
python -m unittest discover tests
```

All external dependencies (PyQt6, pynput, mss, google-genai, openai, anthropic, requests) are fully stubbed so the suite runs in CI without any platform-specific setup. HoverMind uses the built-in `unittest` runner; pytest is not required.

### Project structure

```
HoverMind/
├── hovermind.py          # Single-file application (ScreenCapture, AIAnalyzer,
│                         # FloatingTooltip, MainController, main())
├── tests/
│   └── test_hovermind.py # Unit tests with mocked dependencies
├── docs/
│   └── ARCHITECTURE.md   # Detailed architecture documentation
├── ROADMAP.md            # Planned features and milestones
├── CONTRIBUTING.md       # Contribution guidelines
├── requirements.txt      # Runtime dependencies
├── .env.example          # Environment variable template
└── LICENSE               # MIT License
```

### Coding style

- Follow [PEP 8](https://peps.python.org/pep-0008/) with a maximum line length of 100 characters.
- Public docstrings use NumPy-style sections (`Parameters`, `Returns`) as shown in `hovermind.py`.
- Keep all application logic in `hovermind.py`; platform stubs belong in tests.

---

## 🗺️ Roadmap

See [ROADMAP.md](ROADMAP.md) for the full roadmap with milestones and detailed feature descriptions.

**Highlights:**

- 🔌 **Multi-provider AI** — OpenAI GPT-4o Vision, Anthropic Claude Vision, local Ollama models
- 🖥️ **Cross-platform** — macOS and Linux support
- 🎹 **Custom hotkeys** — user-configurable key combinations
- 📋 **Clipboard integration** — copy the last AI response with one click
- 🗂️ **Analysis history** — searchable log of past hover analyses
- 🖼️ **System tray** — background operation with a tray icon and context menu
- 📦 **Standalone installer** — PyInstaller-built `.exe` for Windows

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

**Quick summary:**

1. Fork the repository and create a feature branch.
2. Write tests for any new or changed behaviour.
3. Ensure `python -m pytest tests/ -v` passes.
4. Open a pull request with a clear description of your changes.

---

## 📄 License

HoverMind is released under the [MIT License](LICENSE).
