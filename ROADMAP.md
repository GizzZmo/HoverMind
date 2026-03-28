# 🗺️ HoverMind Roadmap

This document describes the planned evolution of HoverMind. Items are grouped into milestones ordered roughly by priority and effort. The roadmap is living — community feedback shapes what gets built next.

> **Status key:** ✅ Done · 🚧 In progress · 📋 Planned · 💡 Idea / under consideration

---

## Milestone 1 — Stable Core (v0.1) ✅

The initial working release establishes the foundational pipeline.

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Alt+Shift hotkey activates screen capture | ✅ |
| 1.2 | 500×500 px DPI-aware capture via `mss` | ✅ |
| 1.3 | Google Gemini Vision API integration | ✅ |
| 1.4 | Frameless, semi-transparent PyQt6 tooltip overlay | ✅ |
| 1.5 | Debounced analysis (800 ms default) | ✅ |
| 1.6 | Thread-safe Qt signal/slot architecture | ✅ |
| 1.7 | `.env` / `GEMINI_API_KEY` configuration | ✅ |
| 1.8 | Unit tests with fully mocked dependencies | ✅ |
| 1.9 | Windows DPI awareness (`SetProcessDpiAwareness`) | ✅ |

---

## Milestone 2 — Developer Experience & Polish (v0.2) 📋

Improves usability for end users and lowers the barrier for contributors.

| # | Feature | Status |
|---|---------|--------|
| 2.1 | **System tray icon** — run silently in the background; right-click menu for enable/disable and quit | 📋 |
| 2.2 | **Standalone Windows installer** — PyInstaller-packaged `.exe` with bundled dependencies; no Python required | 📋 |
| 2.3 | **Clipboard copy button** — small "copy" icon in the tooltip to copy the AI response to the clipboard | 📋 |
| 2.4 | **"Loading…" indicator** — show a spinner or progress text in the tooltip while the API request is in flight | 📋 |
| 2.5 | **Configurable debounce delay** — expose the 800 ms wait as a user setting | 📋 |
| 2.6 | **Logging to file** — optional `hovermind.log` for troubleshooting | 📋 |
| 2.7 | **Comprehensive README & docs** — architecture guide, roadmap, contributing guide | ✅ |

---

## Milestone 3 — Multi-Provider AI (v0.3) 📋

Let users choose their preferred AI backend without changing any code.

| # | Feature | Status |
|---|---------|--------|
| 3.1 | **OpenAI GPT-4o Vision** — plug-in via `OPENAI_API_KEY` environment variable | 📋 |
| 3.2 | **Anthropic Claude Vision** — plug-in via `ANTHROPIC_API_KEY` | 📋 |
| 3.3 | **Ollama / local LLM support** — send images to a locally running multimodal model (e.g. LLaVA, BakLLaVA) for fully offline use | 📋 |
| 3.4 | **Provider selection in config** — `AI_PROVIDER=gemini|openai|anthropic|ollama` environment variable | 📋 |
| 3.5 | **Model selection** — `AI_MODEL` environment variable overrides the default model for any provider | 📋 |
| 3.6 | **Pluggable `AnalyzerBase` ABC** — clean abstract interface so third-party providers can be added without touching core code | 📋 |

---

## Milestone 4 — Settings & Personalisation (v0.4) 📋

A lightweight settings panel that eliminates the need to edit source files.

| # | Feature | Status |
|---|---------|--------|
| 4.1 | **Settings window** — accessible from the tray icon; persists to `~/.hovermind/config.json` | 📋 |
| 4.2 | **Custom hotkey** — user-configurable key combination (not just Alt+Shift) | 📋 |
| 4.3 | **Custom AI prompt** — let users write their own system prompt (e.g. "Always reply in French") | 📋 |
| 4.4 | **Snippet size control** — slider for 200 px–1000 px capture region | 📋 |
| 4.5 | **Tooltip theme** — light / dark / system preference | 📋 |
| 4.6 | **Tooltip font size** — configurable label font size | 📋 |
| 4.7 | **Response language** — dropdown to request explanations in any language | 📋 |

---

## Milestone 5 — Analysis History (v0.5) 📋

Keep track of past hover analyses for reference and productivity.

| # | Feature | Status |
|---|---------|--------|
| 5.1 | **Session history panel** — side panel (or separate window) listing recent hover analyses with thumbnail + text | 📋 |
| 5.2 | **Persistent history** — save analyses to an SQLite database at `~/.hovermind/history.db` | 📋 |
| 5.3 | **Search** — full-text search over past analyses | 📋 |
| 5.4 | **Export** — export selected history entries as Markdown or plain text | 📋 |
| 5.5 | **Pinned analyses** — mark important results to keep them out of auto-cleanup | 📋 |

---

## Milestone 6 — Cross-Platform Support (v0.6) 💡

Bring HoverMind to macOS and Linux.

| # | Feature | Status |
|---|---------|--------|
| 6.1 | **macOS port** — replace `SetProcessDpiAwareness` / ctypes Win32 calls with AppKit equivalents; verify `mss` compatibility | 💡 |
| 6.2 | **Linux port** — support X11 via `mss`; handle Wayland limitations (screenshot restrictions) | 💡 |
| 6.3 | **Cross-platform hotkey** — replace or supplement `pynput` with a solution that works reliably under Wayland and macOS accessibility permissions | 💡 |
| 6.4 | **Retina / HiDPI on macOS** — ensure physical-pixel capture matches logical-coordinate cursor position | 💡 |
| 6.5 | **CI matrix** — expand GitHub Actions to run tests on Windows, macOS, and Ubuntu | 💡 |

---

## Milestone 7 — Advanced Interactions (v0.7) 💡

Richer interaction patterns beyond the core hover-and-explain flow.

| # | Feature | Status |
|---|---------|--------|
| 7.1 | **Follow-cursor mode** — continuously refresh the tooltip as the cursor moves (rate-limited) | 💡 |
| 7.2 | **Click-to-freeze** — click to pin a tooltip in place while you continue browsing | 💡 |
| 7.3 | **Region selection** — hold hotkey and drag to define a custom capture region instead of the fixed square | 💡 |
| 7.4 | **Ask a question** — type a question about what you're pointing at (e.g. "How do I fix this error?") | 💡 |
| 7.5 | **Conversation follow-up** — continue chatting about the last captured screenshot | 💡 |
| 7.6 | **Smart content detection** — automatically switch prompt style based on detected content type (code, image, form field, etc.) | 💡 |

---

## Milestone 8 — Performance & Reliability (v0.8) 💡

Harden the application for long-running daily use.

| # | Feature | Status |
|---|---------|--------|
| 8.1 | **Response caching** — avoid re-querying the API when the same screen region is hovered again within a short window | 💡 |
| 8.2 | **API cost tracking** — track approximate token/image usage and display a running total in the tray tooltip | 💡 |
| 8.3 | **Offline detection** — detect no network and show a meaningful message instead of a timeout | 💡 |
| 8.4 | **Memory / CPU profiling** — benchmark and optimise the idle resource footprint | 💡 |
| 8.5 | **Automated integration tests** — end-to-end smoke test that starts the app and performs a real capture (Windows CI only) | 💡 |

---

## Contributing to the Roadmap

Have an idea not listed here? [Open an issue](https://github.com/GizzZmo/HoverMind/issues) with the label **enhancement** and describe your use-case. Upvotes (👍 reactions) help prioritise what to build next.
