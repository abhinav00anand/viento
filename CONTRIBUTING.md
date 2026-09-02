# Contributing to Viento SDK

First off — **thank you** for taking the time to contribute! 🎉

Viento is an open-source project and every contribution matters, whether it's a bug fix, a new backend adapter, documentation improvement, or a fresh test case.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Branch Strategy](#branch-strategy)
- [Commit Convention](#commit-convention)
- [Pull Request Checklist](#pull-request-checklist)
- [Running Tests](#running-tests)
- [Style Guide](#style-guide)
- [Adding a New Backend Adapter](#adding-a-new-backend-adapter)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

---

## Code of Conduct

This project follows our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold its standards.

---

## How to Contribute

### Bug Reports
File a detailed issue at [GitHub Issues](https://github.com/abhinav00anand/zephyr/issues) using the **Bug Report** template. Include:
- Python version, OS, Viento SDK version
- Minimal reproduction steps
- Expected vs actual behavior
- Stack trace (if applicable)

### Feature Requests
Open a [GitHub Discussion](https://github.com/abhinav00anand/zephyr/discussions) or issue using the **Feature Request** template. Describe:
- The problem you're solving
- Your proposed solution
- Alternatives you considered

### Code Contributions
1. Fork the repo and clone it locally.
2. Set up your development environment (see below).
3. Create a focused branch for your change.
4. Write code + tests.
5. Open a Pull Request against `main`.

---

## Development Setup

```bash
# Clone your fork
git clone https://github.com/<your-username>/viento.git
cd viento/SDK

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.\.venv\Scripts\activate       # Windows

# Install in editable mode with dev extras
pip install -e ".[dev]"

# Verify setup
pytest tests/ -v
```

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable release branch |
| `dev` | Integration branch for features |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `refactor/<name>` | Refactoring / cleanup |

Always branch from `main` (or `dev` if working on a feature that builds on unreleased work).

---

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

**Examples:**
```
feat(scheduler): add exponential backoff for job retry
fix(ollama): handle HTTP 503 during model pull gracefully
docs(readme): add async client usage example
test(protocol): add sequence replay attack test case
```

---

## Pull Request Checklist

Before opening a PR, ensure:

- [ ] All existing tests pass: `pytest tests/ -v`
- [ ] New functionality has test coverage
- [ ] Code is formatted: `black viento/`
- [ ] Linting passes: `ruff check viento/`
- [ ] Type hints are present on all public functions
- [ ] Docstrings are complete on all public classes/methods
- [ ] `CHANGELOG.md` is updated under `[Unreleased]`
- [ ] PR description explains the *why*, not just the *what*

---

## Automated AI Reviews (Antigravity)

All Pull Requests are automatically reviewed by the **Antigravity PR Review Agent**:
- **Automated First Pass**: Runs on PR creation and updates, validating against Viento SDK architectural standards, typing, and formatting.
- **On-Demand Review**: Triggered anytime by commenting `@agy /review` on the PR.
- **Deep Check Audit**: Comment `@agy /deepcheck` on the PR to run a rigorous deep audit covering:
  - Canonical Envelope Protocol (V1.0) compatibility
  - Async concurrency, deadlocks, and task leaks
  - WebSocket and stream socket teardown
  - Hardware fallback robustness in telemetry
  - Zero-trust security and credential leaks

See [docs/antigravity_pr_review.md](docs/antigravity_pr_review.md) for full details.

---

## Running Tests

```bash
# Full test suite
pytest tests/ -v

# Specific test file
pytest tests/test_scheduler.py -v

# With coverage report
pytest tests/ --cov=viento --cov-report=html
open htmlcov/index.html

# Fast mode (skip slow integration tests)
pytest tests/ -v -m "not slow"
```

---

## Style Guide

- **Formatter:** `black` (line length 100)
- **Linter:** `ruff`
- **Type hints:** Required on all public APIs
- **Docstrings:** Google style for all public classes/methods
- **Logging:** Use `logging.getLogger("viento.<module>")` — never `print()`
- **Secrets:** Never log or persist raw API keys; use `SecretMasker` from `viento.telemetry.logging`

---

## Adding a New Backend Adapter

1. Create `viento/backends/<name>.py`
2. Implement `InferenceBackend` from `viento.backends.base`:
   - `name()`, `capabilities()`, `health()`, `list_models()`
   - `generate(...)` → must call `handle_callback` **before** blocking I/O
   - `embeddings(...)` → must call `handle_callback` **before** blocking I/O
   - `cancel(job_id)` → must be a no-op if handle-based cancellation is sufficient
3. Implement `ExecutionHandle` with `cancel()` and `is_done()`
4. Add tests to `tests/test_backends.py`
5. Register the adapter in `ConnectionManager` backend selection logic

---

## Reporting Bugs

Use the GitHub Issues bug template. For security vulnerabilities, please email **indrohelpdesk@gmail.com** — **do not** open a public issue.

---

Thank you for being part of the Viento community! 🌊⚡
