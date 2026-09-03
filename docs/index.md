# Viento Documentation

### ⚡ Ultra-Lightweight Distributed Edge Inference Mesh ⚡

[![PyPI](https://img.shields.io/pypi/v/viento.svg?color=blue)](https://pypi.org/project/viento/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/abhinav00anand/viento/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)](https://pypi.org/project/viento/)

**Viento** is an ultra-lightweight distributed AI inference mesh that bridges local and cloud GPU/CPU compute (Ollama, vLLM, llama.cpp) with an OpenAI-compatible API gateway.

---

## 🌟 Key Highlights

- **Zero Inbound Port Forwarding Required**: Nodes establish outbound WebSocket connections (`wss://`) through NATs, firewalls, and dynamic residential IPs.
- **Multi-Backend Agnostic**: Native adapter layer for **Ollama**, **vLLM**, and **llama.cpp**.
- **Pydantic V2 Wire Protocol**: Monotonically sequenced frames with strict validation (`extra="forbid"`).
- **Sub-2ms Cancellation Teardown**: Instant socket-level abortion frees VRAM immediately when queries cancel mid-stream.
- **Hardware Telemetry**: Real-time non-blocking CPU, RAM, and NVIDIA GPU metrics reporting.
- **Standard OpenAI Compatibility**: Direct integration with OpenAI Python SDK, LangChain, and LlamaIndex.

---

## 🚀 Quick Install

Install the canonical package directly from PyPI:

```bash
pip install viento
```

Or install from source in editable mode:

```bash
git clone https://github.com/abhinav00anand/viento.git
cd viento
pip install -e .
```

---

## 🧭 Navigation Guide

- **[Quickstart Guide](quickstart.md)**: Set up your first node in under 2 minutes.
- **[Architecture Deep Dive](architecture.md)**: Protocol design, concurrency bounding, and reconnection backoff.
- **[CLI Reference](cli_guide.md)**: Detailed reference for all `viento` terminal commands.
- **[Ollama Integration](ollama_integration_guide.md)**: Pairing Viento with local Ollama instances.
- **[Complete Run Guide](RUN_GUIDE.md)**: Full guide covering local edge rigs, cloud GPUs, and API querying.
- **[Changelog](changelog.md)**: Release history and version notes.
