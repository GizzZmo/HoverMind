# 🤝 Contributing to HoverMind

Thank you for your interest in contributing! This guide explains how to report bugs, propose features, and submit code changes.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Pull Request Checklist](#pull-request-checklist)
- [Coding Standards](#coding-standards)
- [Running Tests](#running-tests)

---

## Code of Conduct

Be respectful and constructive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) code of conduct.

---

## Reporting Bugs

1. Search [existing issues](https://github.com/GizzZmo/HoverMind/issues) to avoid duplicates.
2. If none exists, open a **Bug report** issue and include:
   - Your OS version and Windows scaling setting
   - Python version (`python --version`)
   - The full traceback / error message
   - Steps to reproduce (as minimal as possible)

---

## Requesting Features

1. Check [ROADMAP.md](ROADMAP.md) — your idea may already be planned.
2. Open a **Feature request** issue. Describe:
   - The problem you are trying to solve
   - How the proposed feature would work from a user perspective
   - Any alternatives you have considered

Upvoting (👍) existing feature requests helps prioritise what gets built.

---

## Development Setup

```bash
# 1. Fork and clone your fork
git clone https://github.com/<your-username>/HoverMind.git
cd HoverMind

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (only needed to run the app, not tests)
```

---

## Making Changes

1. Create a feature branch off `main`:

   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes in `hovermind.py` (or `tests/test_hovermind.py` for test-only changes).

3. Add or update tests for any new or changed behaviour — see [Running Tests](#running-tests).

4. Commit with a clear, imperative message:

   ```
   feat: add clipboard copy button to tooltip
   fix: clamp tooltip position on secondary monitor
   docs: document AI_PROMPT constant
   ```

5. Push your branch and open a pull request against `main`.

---

## Pull Request Checklist

Before marking your PR ready for review, confirm that:

- [ ] `python -m pytest tests/ -v` passes with no failures
- [ ] New public classes / methods have Google-style docstrings
- [ ] No secrets or API keys are committed
- [ ] The PR description explains *what* changed and *why*
- [ ] Relevant documentation (README, ROADMAP) is updated if applicable

---

## Coding Standards

| Rule | Detail |
|------|--------|
| **Style** | [PEP 8](https://peps.python.org/pep-0008/), max line length 100 characters |
| **Type hints** | All function signatures should include type hints (`from __future__ import annotations` is already present) |
| **Docstrings** | Google-style for all public classes and methods |
| **Imports** | Standard library → third-party → local; alphabetical within each group |
| **Platform guards** | Wrap Windows-only code in `if sys.platform == "win32":` blocks |
| **No global state** | Prefer passing dependencies via constructors over module-level mutation |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

The suite is fully headless — it runs on Windows, macOS, and Linux without a display, a real Gemini API key, or any Windows-specific libraries. All heavy dependencies (`PyQt6`, `pynput`, `mss`, `google-genai`) are stubbed before `hovermind` is imported.

To run a single test class:

```bash
python -m pytest tests/test_hovermind.py::TestAIAnalyzer -v
```

---

Thank you for helping make HoverMind better! 🎉
