# Zephyr SDK — Architecture & Design Reference

> **Version**: 0.1.0 | **Target**: Zephyr Cloud `v1` Protocol

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Component Architecture](#2-component-architecture)
3. [End-to-End Data Flow](#3-end-to-end-data-flow)
4. [WSS Protocol Specification](#4-wss-protocol-specification)
5. [Reconnection & Resilience Strategy](#5-reconnection--resilience-strategy)
6. [Backend Selection & Adapter Design](#6-backend-selection--adapter-design)
7. [Telemetry & Observability](#7-telemetry--observability)
8. [Security Model](#8-security-model)
9. [Configuration Reference](#9-configuration-reference)
10. [Deployment Checklist](#10-deployment-checklist)

---

## 1. System Overview

Zephyr is a distributed AI inference mesh that bridges **local GPU nodes** (running Ollama, llama.cpp, or vLLM) with **OpenAI-compatible API consumers** via a cloud relay gateway.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ZEPHYR SYSTEM                                │
│                                                                     │
│  ┌──────────────┐    WSS/TLS     ┌──────────────────────────────┐  │
│  │  SDK Runtime │◄──────────────►│  Cloud Gateway               │  │
│  │  (your GPU)  │                │  (zephyr.onrender.com)        │  │
│  │              │                │                              │  │
│  │  ┌─────────┐ │                │  ┌──────────────────────────┐│  │
│  │  │ Ollama  │ │                │  │  OpenAI-Compatible API   ││  │
│  │  │localhost│ │                │  │  POST /v1/chat/completions││  │
│  │  │  :11434 │ │                │  │  GET  /v1/models         ││  │
│  │  └─────────┘ │                │  │  POST /v1/embeddings     ││  │
│  └──────────────┘                │  └──────────────────────────┘│  │
│                                  └──────────────────────────────┘  │
│                                              ▲                      │
│                                              │ HTTPS + Bearer token │
│                                    ┌─────────────────┐             │
│                                    │  API Consumer   │             │
│                                    │  (your app,     │             │
│                                    │   OpenAI SDK,   │             │
│                                    │   LangChain...) │             │
│                                    └─────────────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

The SDK component on your local machine serves dual purposes:
- **Control plane**: establishes authenticated WebSocket to the Cloud, handles handshake, delivers heartbeats.
- **Data plane**: receives inference job requests over the same WebSocket, executes them against the local Ollama server, and streams token chunks back to the Cloud, which relays them to the waiting HTTP client.

---

## 2. Component Architecture

```
viento/
├── cli/
│   └── main.py          # Click CLI: run, status, models, doctor, config, pull, stop
├── connection/
│   └── manager.py       # ConnectionManager: WSS supervisor, handshake, heartbeat
├── scheduler/
│   └── scheduler.py     # JobScheduler: FIFO queue, semaphore concurrency, deadline
├── backends/
│   ├── base.py          # InferenceBackend ABC
│   ├── ollama.py        # OllamaAdapter (primary) — REST + NDJSON streaming
│   ├── llamacpp.py      # LlamaCppAdapter — /completion + /embedding
│   └── vllm.py          # VLLMAdapter — OpenAI-compatible /v1 endpoints
├── protocol/
│   ├── envelope.py      # Pydantic V2 message models for all 15 frame types
│   └── validator.py     # Serialization, sequence tracking, error mapping
├── telemetry/
│   ├── collector.py     # CPU/GPU/RAM metrics, latency histograms, counters
│   └── logging.py       # Structured JSON logger with secret masking
├── config/
│   ├── loader.py        # ZephyrConfig, RuntimeState, ConfigManager
│   └── defaults.py      # DEFAULT_CONFIG, ENV_VAR_MAPPING, apply_env_overrides
└── client/
    └── client.py        # VientoClient — high-level Python API client
```

### ConnectionManager

`ConnectionManager` is the nerve centre of the SDK runtime. It:

1. Opens an outbound `wss://` connection to the Cloud gateway.
2. Executes the full **HELLO → WELCOME → REGISTER → REGISTER_ACK → SESSION_READY** handshake sequence.
3. Starts a background heartbeat coroutine (15-second cadence by default).
4. Enters a receive loop listening for `job_request`, `cancel_job`, and control frames.
5. Delegates job execution to `JobScheduler` via registered callbacks.
6. Reconnects automatically with exponential backoff + jitter on any connection failure.

### JobScheduler

`JobScheduler` provides bounded FIFO job execution:

- Wraps `asyncio.Semaphore(max_concurrency)` — default 1 concurrent job.
- Background worker loop dequeues jobs and spawns `asyncio.Task` per job.
- Each job runs `_stream_ollama_inference()` with a `wait_for(timeout=job.timeout)` deadline.
- On completion, sends `job_complete` frame back through `ConnectionManager`.
- On timeout/failure, sends `job_error` frame and increments failure counters.

### OllamaAdapter

The primary inference backend. All network I/O is performed with `httpx`:

| Ollama Endpoint | Purpose | Streaming? |
|---|---|---|
| `GET /api/version` | Health check + latency probe | No |
| `GET /api/tags` | List installed models | No |
| `POST /api/show` | Model metadata | No |
| `POST /api/pull` | Download model weights | NDJSON progress |
| `POST /api/chat` | Chat completion | NDJSON tokens |
| `POST /api/embed` | Batch embeddings (new API) | No |
| `POST /api/embeddings` | Single embedding (legacy API) | No |

The adapter performs automatic **context overflow detection** (inspects Ollama error messages for "too long"/"context") and maps all network errors to typed `BackendOfflineError`, `BackendTimeoutError`, `ModelNotFoundError`, `ContextOverflowError`.

---

## 3. End-to-End Data Flow

Below is the complete lifecycle of a single streaming inference request:

```
API Consumer                Cloud Gateway              SDK Runtime           Ollama
────────────               ───────────────            ─────────────         ───────
POST /v1/chat/completions
  Authorization: Bearer zph_tmp_xxx
        │
        ▼
  [validate token SHA-256]
  [check rate limit]
  [resolve runtime session]
        │
        ▼
  dispatch JobRequestFrame
  ──────────────────────────────────────────────────────►
                                                    [scheduler.submit_job()]
                                                    [semaphore acquired]
                                                          │
                                                          ▼
                                                    POST /api/chat (stream)
                                                    ──────────────────────►
                                                                      NDJSON chunk
                                                    ◄──────────────────────
                                                    send TokenChunkFrame
        ◄──────────────────────────────────────────
  SSE: data: {"choices":[{"delta":{"content":"..."}}]}
        │
       ...
                                                          │
                                                    Ollama done: true
                                                    send JobCompleteFrame
        ◄──────────────────────────────────────────
  SSE: data: [DONE]
        │
  HTTP 200 response ends
```

**Key timing characteristics**:
- **TTFT** (time-to-first-token): WSS gateway overhead ≈ 5–15 ms added to Ollama TTFT.
- **Per-token latency**: negligible WSS relay overhead (<1ms per chunk in practice).
- **Job timeout**: 120 seconds by default. Configurable per-request.

---

## 4. WSS Protocol Specification

All frames are JSON objects transmitted as WebSocket text messages. The `type` field (lowercase snake_case) determines the frame class.

### 4.1 Connection Handshake

```
SDK (client)                               Cloud (server)
──────────                                 ──────────────
{"type": "hello",
 "runtime_id": "my-node",
 "version": "0.1.0"}
                                ─────────►
                                           {"type": "welcome",
                                            "session_id": "sess_abc123",
                                            "heartbeat_interval": 30,
                                            "status": "connected"}
                                ◄─────────
{"type": "register",
 "runtime_name": "my-node",
 "hardware": {
   "gpu_model": "RTX 4090",
   "vram_mb": 24576,
   "ram_mb": 65536,
   "device_count": 1,
   "max_sequence_length": 8192
 },
 "supported_models": ["llama3:latest", "phi3:latest"]}
                                ─────────►
                                           {"type": "register_ack",
                                            "session_id": "sess_abc123",
                                            "status": "registered",
                                            "registered_models": ["llama3:latest"]}
                                ◄─────────
                                           {"type": "session_ready",
                                            "session_id": "sess_abc123",
                                            "api_key": "zph_tmp_a1b2c3...",
                                            "expires_at": 1720000000.0,
                                            "ttl_seconds": 3600}
                                ◄─────────
[Node now active. Key displayed in terminal.]
```

### 4.2 Heartbeat

```
SDK                                        Cloud
{"type": "heartbeat",
 "session_id": "sess_abc123",
 "timestamp": 1720000015.0,
 "active_jobs": 0}
                                ─────────►
                                           {"type": "heartbeat_ack",
                                            "timestamp": 1720000015.1}
                                ◄─────────
```

Heartbeat deadline: **45 seconds**. If the Cloud does not receive a heartbeat within this window, the session is marked offline and evicted from the active runtime pool.

### 4.3 Inference Job Lifecycle

```
Cloud                                      SDK
{"type": "job_request",
 "job_id": "job_xyz",
 "session_id": "sess_abc123",
 "model": "llama3:latest",
 "messages": [...],
 "temperature": 0.7,
 "max_tokens": 512,
 "stream": true}
                                ─────────►

[For each generated token:]
                                           {"type": "token_chunk",
                                            "job_id": "job_xyz",
                                            "delta": "Hello",
                                            "index": 0,
                                            "finish_reason": null}
                                ◄─────────

[When generation is complete:]
                                           {"type": "job_complete",
                                            "job_id": "job_xyz",
                                            "finish_reason": "stop",
                                            "prompt_tokens": 42,
                                            "completion_tokens": 128,
                                            "total_tokens": 170}
                                ◄─────────

[On error:]
                                           {"type": "job_error",
                                            "job_id": "job_xyz",
                                            "error_message": "context length exceeded",
                                            "error_code": "context_overflow"}
                                ◄─────────
```

### 4.4 Cancellation

```
Cloud                                      SDK
{"type": "cancel_job",
 "job_id": "job_xyz",
 "reason": "client_disconnected"}
                                ─────────►
[OllamaAdapter._cancelled_jobs.add(job_id)]
[Next token iteration skips and breaks]
```

---

## 5. Reconnection & Resilience Strategy

The `ConnectionManager.start()` loop implements **exponential backoff with additive jitter**:

```
sleep = min(max_delay, base_delay × 2^attempt + jitter)
jitter = random.uniform(-0.2, 0.2) × base_delay × 2^attempt
```

| Attempt | Base Delay | Jitter Range | Actual Sleep |
|---------|-----------|--------------|--------------|
| 1 | 1s | ±0.2s | 0.8–1.2s |
| 2 | 2s | ±0.4s | 1.6–2.4s |
| 3 | 4s | ±0.8s | 3.2–4.8s |
| 4 | 8s | ±1.6s | 6.4–9.6s |
| 5 | 16s | ±3.2s | 12.8–19.2s |
| 6+ | 30s | ±6s | 24–30s (capped) |

On **successful TCP connection**, backoff resets to base. This prevents thundering herd when the Cloud restarts after a deployment.

---

## 6. Backend Selection & Adapter Design

```python
class InferenceBackend(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def capabilities(self) -> List[str]: ...

    @abstractmethod
    def list_models(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def generate(self, request, callbacks) -> JobCompletePayload: ...

    @abstractmethod
    def embeddings(self, model, prompt) -> EmbeddingResponsePayload: ...

    @abstractmethod
    def cancel(self, job_id: str) -> bool: ...

    @abstractmethod
    def health(self) -> Dict[str, Any]: ...
```

| Adapter | Primary Endpoint | Models | Notes |
|---------|-----------------|--------|-------|
| **OllamaAdapter** | `http://localhost:11434` | All Ollama models | **Default**. NDJSON streaming, `/api/chat` |
| **LlamaCppAdapter** | `http://localhost:8080` | GGUF models | `/completion` + `/embedding` |
| **VLLMAdapter** | `http://localhost:8000/v1` | Any HF model | OpenAI-compatible `/v1/chat/completions` |

---

## 7. Telemetry & Observability

`TelemetryCollector` gathers metrics in-process:

- **Latency histograms** (p50/p95/p99 via bucket counting)
- **Request counters** (total, success, error) per model
- **Hardware snapshots** (CPU %, RAM %, GPU VRAM via pynvml)
- **Secret masking** — all log lines are filtered through `SecretMasker` which replaces `zph_tmp_[a-f0-9]+` patterns with `zph_tmp_***`

Logs are emitted as structured JSON when `log_json=true`, enabling ingestion by Datadog, Loki, or Cloud Logging.

---

## 8. Security Model

| Layer | Mechanism |
|-------|-----------|
| Transport | TLS 1.2+ enforced by Render/Cloudflare |
| Authentication | SHA-256 hashed tokens at rest, `zph_tmp_` prefix format validation |
| Authorization | 1-hour TTL, automatic expiry sweep in KeyStore |
| Rate limiting | Sliding-window 60 RPM per token hash |
| Body size | 4MB hard cap enforced in middleware before routing |
| Secret logging | All log lines scrubbed for `zph_tmp_*` patterns |
| Prompt isolation | Each job runs in a fresh Ollama context (no session state leak) |

---

## 9. Configuration Reference

| Key | Env Var | Default | Description |
|-----|---------|---------|-------------|
| `server_url` | `ZEPHYR_SERVER_URL` | `wss://zephyr.onrender.com/ws/runtime` | Cloud WSS gateway URL |
| `http_url` | `ZEPHYR_HTTP_URL` | `https://zephyr.onrender.com` | Cloud HTTP base URL |
| `ollama_url` | `ZEPHYR_OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `node_name` | `ZEPHYR_NODE_NAME` | `zephyr-node` | Node identifier in Cloud |
| `max_concurrency` | `ZEPHYR_MAX_CONCURRENCY` | `1` | Max simultaneous jobs |
| `heartbeat_interval` | `ZEPHYR_HEARTBEAT_INTERVAL` | `15` | Seconds between heartbeats |
| `heartbeat_deadline` | `ZEPHYR_HEARTBEAT_DEADLINE` | `45` | Server eviction timeout |
| `job_timeout` | `ZEPHYR_JOB_TIMEOUT` | `120` | Per-job deadline (seconds) |
| `max_queue_depth` | `ZEPHYR_MAX_QUEUE_DEPTH` | `50` | Max queued jobs per runtime |
| `token_ttl` | `ZEPHYR_TOKEN_TTL` | `3600` | API key lifetime (seconds) |
| `log_level` | `ZEPHYR_LOG_LEVEL` | `INFO` | Python logging level |
| `log_json` | `ZEPHYR_LOG_JSON` | `false` | Emit structured JSON logs |
| `reconnect_base_delay` | `ZEPHYR_RECONNECT_BASE_DELAY` | `1.0` | First backoff delay (s) |
| `reconnect_max_delay` | `ZEPHYR_RECONNECT_MAX_DELAY` | `30.0` | Maximum backoff delay (s) |

Set via `~/.viento/config.toml` or environment variables (env vars take precedence).

---

## 10. Deployment Checklist

Before running `viento run` in production:

- [ ] Ollama is installed and `ollama serve` is running (`viento doctor` to verify)
- [ ] At least one model is downloaded: `viento pull llama3:latest`
- [ ] `viento config set server_url wss://zephyr.onrender.com/ws/runtime`
- [ ] `viento run` executed — note the `zph_tmp_...` key from the handshake panel
- [ ] API consumers configured with `Authorization: Bearer zph_tmp_...`
- [ ] Key TTL monitored — re-run `viento run` before 1-hour expiry or build key refresh into consumer
- [ ] `ZEPHYR_LOG_JSON=true` if shipping logs to an aggregation service

---

*This document is auto-maintained. For protocol changes, update both this document and `Private/protocol_specs/schemas.json`.*
