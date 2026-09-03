# 📜 Changelog

All notable changes to the **Viento SDK** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.12] — 2026-09-03

### 🔒 Security & Credential Hardening
- Sanitized hardcoded credentials from test scripts and switched all remote operations to environment variables (`LIGHTNING_AUTH_TOKEN`, `LIGHTNING_USER_ID`).
- Synchronized README benchmark tables and visuals directly with measured in-memory scheduler stress test outputs.
- Clarified historical cloud GPU benchmark numbers and updated CLI reference table.
- Added native Read the Docs (`.readthedocs.yaml` & `mkdocs.yml`) configuration.

---

## [0.4.0] — 2026-09-02

### 🚀 Major Architectural & Reliability Upgrades
- **Canonical Architecture:** Eliminated duplicate `SDK/` directory. Root `/viento/` is now the single canonical package installable via `pip install -e .` or `pip install viento`.
- **Runtime Bootstrap Key Wiring:** Added `VIENTO_BOOTSTRAP_KEY` to `ENV_VAR_MAPPING` and centralized configuration loading with strict precedence: `CLI Flags > Environment Variables > Config File > Defaults`.
- **Multi-Backend CLI Support:** Added `--backend <ollama|vllm|llamacpp>`, `--vllm-url`, and `--llamacpp-url` CLI arguments with accurate dynamic adapter URL dispatching.
- **Real Process Control in `viento stop`:** Upgraded `viento stop` from a file-state toggle to authentic process lifecycle management. Tracks PID in `RuntimeState`, validates process command-line identity to guard against PID reuse, and sends graceful `SIGTERM` (with fallback to `kill()`).
- **Authentic Scheduler Stress Benchmark:** Overhauled `scripts/run_stress_benchmark_suite.py` to drive real in-memory async execution through `JobScheduler`, `ProtocolEnvelope`, and concurrency semaphores with wall-clock latency profiling and synchronized visual generation.
- **Packaging Modernization:** Migrated to SPDX `license = "MIT"`, removed deprecated classifiers, and enabled dynamic `__version__` resolution via `importlib.metadata`.
- **Test Suite Expansion:** Expanded test matrix to 82/82 passing unit and stress tests.

---

## [0.3.1] — 2026-08-28

### Fixed
- Fixed NVML handle leak in `TelemetryCollector` when querying multiple GPUs.
- Hardened connection manager exponential backoff jitter factor and reconnect state transitions.

---

## [0.3.0] — 2026-08-20

### Added
- Upgraded wire protocol to canonical Pydantic V2 envelope with strict validation and `extra="forbid"`.
- Added logical-session sequence validation in `ConnectionManager`.
- Wired support for Render production gateway at `https://viento.onrender.com`.

---

## [0.2.0] — 2026-08-13

### Major Changes
- **Cancellation Architecture Overhaul**: `CANCEL_ACK` is sent after underlying execution is fully terminated.
- **Job State Machine**: Introduced explicit 6-state `JobStatus` enum (`QUEUED → RUNNING → CANCEL_REQUESTED → CANCELLED / COMPLETED / FAILED`).
- **Queue Safety**: Monotonic sequencing and queue capacity enforcement.
