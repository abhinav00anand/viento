# Changelog

All notable changes to the **Viento SDK** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

### 🚀 Major Changes

#### Cancellation Architecture Overhaul (P0 Fix)
- **BREAKING FIX:** `CANCEL_ACK` is now sent **after** the underlying execution is fully terminated, not upon receipt of `CANCEL_JOB`. This corrects the broken wire semantics where the cloud received confirmation before the job was actually stopped.
- **FIX:** Queued jobs are now properly cancelled before they ever reach the backend. The scheduler inspects `JobStatus` at dequeue time and skips `CANCELLED`/`CANCEL_REQUESTED` jobs — preventing the previous race where queued jobs could execute after cancellation.
- **FIX:** Embedding cancellation now uses real `ExecutionHandle` instances. `handle_callback` is called **before** the blocking HTTP read, ensuring the handle is registered and the TCP stream can be aborted immediately when `CANCEL_JOB` arrives.
- **FIX:** `JobScheduler.stop()` now tracks all active `asyncio.Task` objects in `_active_tasks` and awaits their completion via `asyncio.gather`, preventing the previous race where the event loop could exit with running job tasks.

#### Job State Machine (6-State)
- Introduced explicit `JobStatus` enum: `QUEUED → RUNNING → CANCEL_REQUESTED → CANCELLED / COMPLETED / FAILED`
- State transitions are now monotonic: a `COMPLETED` event cannot overwrite a `CANCEL_REQUESTED` state (the terminal state of the cancel path wins).
- `cancel_job()` now correctly sets `CANCEL_REQUESTED` (not `CANCELLED`) for running jobs, allowing the executing task to observe the flag and complete teardown before marking final state.

#### Queue Safety
- Queue purge in `stop()` uses `get_nowait()` + `task_done()` loop — no internal asyncio.Queue manipulation.
- `submit_job()` sends `JOB_ACK` only **after** successful `queue.put_nowait()` — atomic enqueue guarantees.
- `QueueFull` correctly sends `JOB_ERROR` with `error_code="queue_full"` instead of `JOB_ACK`.

### Added
- `ExecutionHandle` abstract base with `cancel()` and `is_done()` methods.
- `OllamaExecutionHandle` with thread-safe `cancel()` using `response.close()` and `threading.Lock`.
- `handle_callback` parameter on `InferenceBackend.generate()` and `.embeddings()` — both Ollama and fallback adapters implement this.
- `LlamaCppAdapter` and `VLLMAdapter` with stub `cancel()` and embedding `handle_callback` wiring.
- `SequenceTracker` and `ProtocolValidator` in `protocol/validator.py`.
- `TelemetryCollector` with CPU/RAM/GPU metrics, latency histograms, and request counters.
- `SecretMasker` in `telemetry/logging.py` — masks `vnt_tmp_...` patterns in all log output.
- Full `VientoClient` and `AsyncVientoClient` with OpenAI-compatible interface.
- CLI commands: `run`, `status`, `models`, `pull`, `doctor`, `config`, `stop`.
- 47-test suite covering all subsystems with 100% pass rate.

### Fixed
- Session key (`active_key`) is stripped before `RuntimeState` is serialized to disk.
- `ConnectionManager` bootstraps correctly with `VientoConfig` default values.
- Ollama embedding fallback from `/api/embeddings` to `/api/embed` on HTTP error.
- `ProtocolEnvelope.to_json()` correctly serializes `FrameType` enum values as strings.
- `ProtocolEnvelope.from_json()` correctly handles all registered frame types.

---

## [0.1.0] — 2026-08-12

### Added
- Initial SDK scaffold: `ConnectionManager`, `JobScheduler`, `ConfigManager`.
- `OllamaAdapter` with streaming generation and embedding support.
- `ProtocolEnvelope` v1.0 models for all 17 frame types.
- `CLI` entry point with `run`, `status`, `doctor`, `models`, `pull`, `config`, `stop`.
- Basic test suite (33 tests).
- `pyproject.toml`, `README.md`, `docs/` directory.

---

[Unreleased]: https://github.com/abhinav00anand/viento/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/abhinav00anand/viento/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/abhinav00anand/viento/releases/tag/v0.1.0
