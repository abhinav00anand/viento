<div align="center">

```
 __      __  .___  ___________  _______  ___________  ________
/  \    /  \ |   | \_   _____/  \      \ \__    ___/  \_____  \
\   \/\/   / |   |  |    __)_   /   |   \  |    |      /   |   \
 \        /  |   |  |        \ /    |    \ |    |     /    |    \
  \__/\  /   |___| /_______  / \____|__  / |____|     \_______  /
       \/                  \/          \/                     \/

         Distributed AI Inference · Edge-to-Cloud · Open Source
```

<h1>Viento SDK</h1>

<p>
  <strong>Run your local LLMs. Connect to the cloud mesh. Serve the world.</strong>
</p>

[![PyPI version](https://img.shields.io/pypi/v/viento.svg?style=flat-square&color=blue&label=PyPI)](https://pypi.org/project/viento/)
[![Python Versions](https://img.shields.io/pypi/pyversions/viento.svg?style=flat-square)](https://pypi.org/project/viento/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-47%20passed-brightgreen?style=flat-square)](tests/)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg?style=flat-square)](https://github.com/psf/black)
[![GitHub Stars](https://img.shields.io/github/stars/ZephyrCloud-AI/viento?style=flat-square)](https://github.com/ZephyrCloud-AI/viento)

</div>

---

## ⚡ What is Zephyr?

**Zephyr** is a production-grade distributed inference runtime. It lets you take your local GPU/CPU machine running [Ollama](https://ollama.ai), [llama.cpp](https://github.com/ggerganov/llama.cpp), or [vLLM](https://github.com/vllm-project/vllm) and plug it into the Zephyr Cloud mesh — instantly turning it into a globally-addressable AI inference node.

Once connected, any client with a session key can hit your node through the standard **OpenAI-compatible API** (`/v1/chat/completions`, `/v1/embeddings`, `/v1/models`) — from anywhere on the internet.

```
Your Machine (GPU/CPU)          Zephyr Cloud Gateway          Your Users
────────────────────           ────────────────────          ────────────
 Ollama llama3:latest   ◄─WSS─►  zephyr-i2ho.onrender.com  ◄─HTTPS─►  API Clients
 llama.cpp phi3          secure    job routing &          OpenAI-compatible
 vLLM mistral           tunnel    load balancing          SDK / curl / apps
```

---

## 🚀 Installation

```bash
pip install viento
```

Or install from source for the latest unreleased features:

```bash
git clone https://github.com/ZephyrCloud-AI/viento.git
cd viento/SDK
pip install -e ".[dev]"
```

**Requirements:** Python ≥ 3.9 · [Ollama](https://ollama.ai) (recommended) or llama.cpp / vLLM

---

## 🖥 CLI Reference

### Start Your Node

```bash
viento run
```

Boots the runtime, connects to `wss://zephyr-i2ho.onrender.com/ws/runtime`, performs the HELLO→WELCOME→REGISTER→SESSION_READY handshake, and begins receiving jobs. On success, your terminal displays:

```
╔══════════════════════════════════════════════════════════════╗
║               ⚡  ZEPHYR NODE AUTHENTICATED  ⚡              ║
╠══════════════════════════════════════════════════════════════╣
║  Session ID  : zph_sess_8f9a12c4                            ║
║  API Key     : zph_tmp_8f9a2b4c...  (1-hour TTL)           ║
║  Models      : llama3:latest, phi3:mini, mistral:7b         ║
║  Backend     : Ollama @ http://localhost:11434               ║
║  Status      : 🟢 Online — awaiting jobs                    ║
╚══════════════════════════════════════════════════════════════╝
```

### All Commands

| Command | Description |
|---------|-------------|
| `viento run` | Start the runtime node and connect to cloud |
| `viento run --server wss://...` | Connect to a custom gateway |
| `viento run --concurrency 4` | Override max concurrent jobs |
| `viento status` | Show session, TTL, active jobs, and metrics |
| `viento models` | List all locally discovered models |
| `viento pull llama3:latest` | Pull model weights via Ollama |
| `viento doctor` | Diagnose Ollama, GPU, RAM, and network |
| `viento config view` | View current configuration |
| `viento config set <key> <value>` | Update a config value |
| `viento stop` | Gracefully drain jobs and disconnect |

---

## 🐍 Python Client Usage

### Synchronous Chat

```python
from viento.client.client import VientoClient

client = VientoClient(
    base_url="https://zephyr-i2ho.onrender.com",
    api_key="zph_tmp_your_session_key",
)

response = client.chat.completions.create(
    model="llama3:latest",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user",   "content": "Explain quantum entanglement."},
    ],
    temperature=0.7,
    max_tokens=512,
)

print(response.choices[0].message.content)
```

### Streaming (Real-Time Tokens)

```python
stream = client.chat.completions.create(
    model="llama3:latest",
    messages=[{"role": "user", "content": "Write a haiku about distributed systems."}],
    stream=True,
)

for chunk in stream:
    print(chunk.choices[0].delta.content, end="", flush=True)
```

### Async Client

```python
import asyncio
from viento.client.client import AsyncVientoClient

async def main():
    client = AsyncVientoClient(api_key="zph_tmp_...")
    response = await client.chat.completions.create(
        model="phi3:latest",
        messages=[{"role": "user", "content": "Hello, Zephyr!"}],
    )
    print(response.choices[0].message.content)

asyncio.run(main())
```

### Embeddings

```python
result = client.embeddings.create(
    model="all-minilm:latest",
    input=["The quick brown fox", "jumps over the lazy dog"],
)

for i, embedding in enumerate(result.data):
    print(f"Input {i}: {len(embedding.embedding)}-dim vector")
```

---

## 🏗 Architecture

```
                    ┌─────────────────────────────────────────┐
                    │           Zephyr Cloud Gateway          │
                    │     wss://zephyr-i2ho.onrender.com           │
                    │                                         │
                    │  ┌──────────┐  ┌──────────────────────┐ │
                    │  │  API GW  │  │  RuntimeManager      │ │
                    │  │ /v1/chat │  │  - Session Registry  │ │
                    │  │ /v1/emb  │  │  - Job Routing       │ │
                    │  │ /v1/models│ │  - Heartbeat Monitor │ │
                    │  └──────────┘  └──────────────────────┘ │
                    └──────────────────┬──────────────────────┘
                                       │
                               WSS · ProtocolEnvelope v1.0
                               (HELLO/WELCOME/REGISTER/JOB/...)
                                       │
         ┌─────────────────────────────▼───────────────────────────────┐
         │                     Zephyr Edge Node                        │
         │                                                             │
         │   ┌─────────────────────┐     ┌───────────────────────────┐ │
         │   │  ConnectionManager  │────►│       JobScheduler        │ │
         │   │  ▸ WSS Client       │     │  ▸ FIFO async queue       │ │
         │   │  ▸ Exponential BO   │     │  ▸ Semaphore concurrency  │ │
         │   │  ▸ Heartbeat 15s    │     │  ▸ ExecutionHandle cancel │ │
         │   │  ▸ Seq. Validation  │     │  ▸ State machine (6 states│ │
         │   └──────────┬──────────┘     └────────────┬──────────────┘ │
         │              │                             │                 │
         │   ┌──────────▼──────────┐    ┌────────────▼──────────────┐  │
         │   │   ConfigManager     │    │    Inference Backends      │  │
         │   │  ~/.viento/         │    │  ▸ OllamaAdapter          │  │
         │   │    config.toml      │    │  ▸ LlamaCppAdapter        │  │
         │   │    runtime.json     │    │  ▸ VLLMAdapter            │  │
         │   └─────────────────────┘    └───────────────────────────┘  │
         │                                                             │
         │   ┌──────────────────────────────────────────────────────┐  │
         │   │                  TelemetryCollector                  │  │
         │   │   CPU · RAM · GPU VRAM · Latency Histograms · Logs   │  │
         │   └──────────────────────────────────────────────────────┘  │
         └─────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Location | Role |
|-----------|----------|------|
| `ConnectionManager` | `viento/connection/manager.py` | WSS supervisor, handshake, heartbeat, reconnect |
| `JobScheduler` | `viento/scheduler/scheduler.py` | FIFO queue, semaphore, cancellation state machine |
| `OllamaAdapter` | `viento/backends/ollama.py` | NDJSON streaming, TCP-abort cancellation |
| `LlamaCppAdapter` | `viento/backends/llamacpp.py` | llama.cpp server v1/chat/completions |
| `VLLMAdapter` | `viento/backends/vllm.py` | vLLM OpenAI-compat endpoint |
| `ProtocolEnvelope` | `viento/protocol/envelope.py` | Canonical WSS framing (v1.0) |
| `TelemetryCollector` | `viento/telemetry/collector.py` | Hardware stats + latency histograms |
| `ConfigManager` | `viento/config/loader.py` | Persistent config, secure key stripping |
| `VientoClient` | `viento/client/client.py` | OpenAI-compatible Python client |

---

## 📁 Repository Structure

```
SDK/
├── 📄 pyproject.toml          ← Package metadata & tooling
├── 📄 README.md               ← This file
├── 📄 CHANGELOG.md            ← Release history
├── 📄 CONTRIBUTING.md         ← Contribution guide
├── 📄 CODE_OF_CONDUCT.md      ← Community standards
│
├── 📂 viento/             ← Main package source
│   ├── 📄 __init__.py
│   ├── 📂 backends/           ← Inference engine adapters
│   │   ├── 📄 base.py         ← Abstract base + handles
│   │   ├── 📄 ollama.py       ← Ollama REST adapter
│   │   ├── 📄 llamacpp.py     ← llama.cpp adapter
│   │   └── 📄 vllm.py         ← vLLM adapter
│   ├── 📂 cli/                ← CLI commands
│   │   ├── 📄 main.py         ← Click group entry point
│   │   └── 📄 commands.py     ← run, status, models, pull ...
│   ├── 📂 client/             ← Python SDK client
│   │   └── 📄 client.py       ← VientoClient / AsyncVientoClient
│   ├── 📂 config/             ← Config & state management
│   │   └── 📄 loader.py       ← ConfigManager, RuntimeState
│   ├── 📂 connection/         ← WebSocket supervisor
│   │   └── 📄 manager.py      ← ConnectionManager
│   ├── 📂 protocol/           ← Wire protocol engine
│   │   ├── 📄 envelope.py     ← Pydantic envelope models
│   │   └── 📄 validator.py    ← Sequence tracking & validation
│   ├── 📂 scheduler/          ← Job queue and executor
│   │   └── 📄 scheduler.py    ← JobScheduler (6-state machine)
│   └── 📂 telemetry/          ← Observability layer
│       ├── 📄 collector.py    ← Hardware + latency metrics
│       └── 📄 logging.py      ← JSON logger with secret masking
│
├── 📂 tests/                  ← Test suite (47 tests, 100% pass)
│   ├── 📄 test_backends.py
│   ├── 📄 test_ollama_adapter.py
│   ├── 📄 test_protocol.py
│   ├── 📄 test_sdk.py
│   └── 📄 test_telemetry.py
│
└── 📂 docs/                   ← Extended documentation
    ├── 📄 architecture.md
    ├── 📄 cli_guide.md
    └── 📄 ollama_integration_guide.md
```

---

## 🔐 Security Design

- **No secrets on disk:** Active API keys (`zph_tmp_...`) are kept only in process memory. The `RuntimeState` model strips keys before any disk write.
- **TLS by default:** All cloud connections use `wss://` (WebSocket Secure).
- **Secret masking in logs:** The `SecretMasker` regex masks any `zph_tmp_...` pattern in structured logs.
- **Sequence validation:** The `SequenceTracker` detects replay attacks and packet reordering in both directions.
- **Connection isolation:** Each WSS session uses a unique `session_id`; unauthorized frame injection is rejected at the envelope level.

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run full test suite
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=viento --cov-report=html
```

**Test Coverage Summary:**

| Module | Tests |
|--------|-------|
| Backend Adapters (Ollama, llama.cpp, vLLM) | 14 tests |
| Protocol Envelopes & Sequence Tracking | 16 tests |
| Scheduler, Config, Connection, Client | 9 tests |
| Telemetry & Logging | 8 tests |
| **Total** | **47 tests · 100% passing** |

---

## 🤝 Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/amazing-feature`
3. Run the tests: `pytest tests/`
4. Push and open a Pull Request

---

## 📜 License

MIT License © 2026 Zephyr Cloud Team. See [LICENSE](../LICENSE) for details.

---

<div align="center">

Made with ⚡ by the Zephyr Cloud team.

[⭐ Star us on GitHub](https://github.com/ZephyrCloud-AI/viento) · [📦 PyPI Package](https://pypi.org/project/viento/) · [🐛 Report a Bug](https://github.com/ZephyrCloud-AI/viento/issues)

</div>
