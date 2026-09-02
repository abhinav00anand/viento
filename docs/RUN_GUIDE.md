# 📖 Viento Mesh: Comprehensive Operator & Execution Guide

This document provides complete, step-by-step instructions for installing, configuring, running, and testing the **Viento Distributed Edge Inference Mesh**.

---

## 📑 Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Component 1: Cloud Control Plane Gateway](#3-component-1-cloud-control-plane-gateway)
4. [Component 2: Inference Engines (Ollama / vLLM / HuggingFace)](#4-component-2-inference-engines)
5. [Component 3: Viento Edge Runtime Node](#5-component-3-viento-edge-runtime-node)
6. [Component 4: Querying via OpenAI-Compatible API](#6-component-4-querying-via-openai-compatible-api)
7. [Cloud GPU Deployment (Lightning AI / Kaggle)](#7-cloud-gpu-deployment-lightning-ai--kaggle)
8. [Running Test Suites & Concurrency Benchmarks](#8-running-test-suites--concurrency-benchmarks)
9. [Troubleshooting & FAQ](#9-troubleshooting--faq)

---

## 1. Architecture Overview

```
 [Clients / Apps / OpenAI SDK]
              │ (HTTPS / SSE Streaming)
              ▼
   ┌────────────────────────────────────────────────────────┐
   │       Viento Cloud Gateway (FastAPI / Uvicorn)         │
   │  • POST /v1/chat/completions (OpenAI Compatible)       │
   │  • Zero-Trust Session KeyStore (vnt_tmp_... 1hr TTL)   │
   │  • Atomic Multi-Tier Capacity Dispatcher               │
   │  • Bidirectional WebSocket Endpoint (/ws/runtime)      │
   └──────────────────────────┬─────────────────────────────┘
                              │ (Secure WSS Tunnel - Pydantic V2 Envelopes)
              ┌───────────────┴───────────────┐
              ▼                               ▼
   ┌────────────────────────┐      ┌────────────────────────┐
   │  Local Edge Rig (SDK)  │      │ Cloud GPU (Tesla T4)   │
   │  • Viento Runtime Node │      │ • Viento Runtime Node  │
   │  • Ollama (llama3:8b)  │      │ • vLLM / PyTorch FP16  │
   └────────────────────────┘      └────────────────────────┘
```

---

## 2. Prerequisites & System Requirements

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **Python** | 3.10+ | 3.11 or 3.12 |
| **Memory** | 8 GB RAM | 16 GB+ RAM |
| **GPU (Optional)** | CPU-only supported | NVIDIA GPU (T4, L4, A100, RTX 3060+) with CUDA |
| **OS** | Linux, macOS, or Windows (WSL2 / PowerShell) | Linux (Ubuntu 22.04+) or macOS |

---

## 3. Component 1: Cloud Control Plane Gateway

The Cloud Control Plane receives HTTP inference requests from users, mints temporary cryptographic keys, and dispatches requests across active WebSocket worker sessions.

### Local Development Setup:

```bash
# Navigate to the Cloud directory
cd Cloud

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
export VIENTO_ENV=development
export VIENTO_BOOTSTRAP_KEY=viento_dev_secret_key_2026
export VIENTO_PORT=10000

# (On Windows PowerShell)
# $env:VIENTO_ENV="development"
# $env:VIENTO_BOOTSTRAP_KEY="viento_dev_secret_key_2026"
# $env:VIENTO_PORT="10000"

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```

### Server Endpoints:
- **Interactive Swagger Docs**: `http://localhost:10000/docs`
- **ReDoc Documentation**: `http://localhost:10000/redoc`
- **Health Probe**: `http://localhost:10000/healthz` (Returns active runtime count)
- **Runtime WebSocket**: `ws://localhost:10000/ws/runtime`

---

## 4. Component 2: Inference Engines

### Option A: Ollama (Recommended for Local Workstations)
1. Download from [ollama.ai](https://ollama.ai).
2. Start the daemon:
   ```bash
   ollama serve
   ```
3. Pull desired model weights:
   ```bash
   ollama pull llama3:latest
   ollama pull phi3:mini
   ```

### Option B: vLLM (Recommended for High-Throughput Cloud GPUs)
```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-0.5B-Instruct \
    --port 8000 \
    --dtype float16
```

---

## 5. Component 3: Viento Edge Runtime Node

The `viento` SDK connects to the cloud gateway, authenticates via `VIENTO_BOOTSTRAP_KEY`, registers hardware capabilities and discovered models, and receives incoming jobs.

```bash
# Install the SDK in editable mode
pip install -e SDK/

# Set the bootstrap secret matching your Cloud Server
export VIENTO_BOOTSTRAP_KEY=viento_dev_secret_key_2026

# Connect to the local Cloud Server
viento run --server ws://localhost:10000/ws/runtime

# Or connect to production cloud mesh:
# viento run --server wss://viento.onrender.com/ws/runtime
```

### Node Authentication Banner:
Upon successful registration, you will see:
```text
╔══════════════════════════════════════════════════════════════╗
║               ⚡  VIENTO NODE AUTHENTICATED  ⚡              ║
╠══════════════════════════════════════════════════════════════╣
║  Session ID  : vnt_sess_7a3d12c8                            ║
║  API Key     : vnt_tmp_9e8f1b2c4d5a... (1-hour TTL)         ║
║  Models      : llama3:latest, phi3:mini                     ║
║  Backend     : Ollama @ http://localhost:11434               ║
║  Capacity    : Max 2 concurrent jobs                         ║
║  Status      : 🟢 Online — awaiting mesh jobs               ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 6. Component 4: Querying via OpenAI-Compatible API

### Using cURL:
```bash
curl -N http://localhost:10000/v1/chat/completions \
  -H "Authorization: Bearer vnt_tmp_YOUR_SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3:latest",
    "messages": [
      {"role": "user", "content": "Explain distributed systems in 3 bullet points."}
    ],
    "stream": true,
    "temperature": 0.7
  }'
```

### Using Python OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:10000/v1",
    api_key="vnt_tmp_YOUR_SESSION_KEY"
)

response = client.chat.completions.create(
    model="llama3:latest",
    messages=[
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Write a short poem about the night sky."}
    ],
    stream=True
)

for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
print()
```

---

## 7. Cloud GPU Deployment (Lightning AI / Kaggle)

You can spin up an NVIDIA Tesla T4 or L4 GPU in seconds using the official Lightning AI SDK:

```python
from lightning_sdk.lightning_cloud.login import Auth
from lightning_sdk import Studio, Machine

# 1. Authenticate with your Lightning API key
auth = Auth()
auth.save(user_id="YOUR_USER_ID", auth_token="sk-lit-YOUR_KEY")

# 2. Provision and start Studio on Tesla T4
studio = Studio(
    name="viento-gpu-worker",
    teamspace="YOUR_TEAMSPACE",
    user="YOUR_USERNAME",
    create_ok=True
)
studio.start(machine=Machine.T4)

# 3. Clone and boot the node
print(studio.run("""
git clone https://github.com/abhinav00anand/zephyr.git
cd viento
pip install -e SDK/
viento run --server wss://viento.onrender.com/ws/runtime
"""))

# 4. Stop Studio when finished to conserve credits
studio.stop()
```

---

## 8. Running Test Suites & Concurrency Benchmarks

### Unit Tests:
```bash
# Cloud Gateway Tests
pytest Cloud/tests/ -v

# SDK & Adapter Tests
pytest SDK/tests/ -v
```

### Advanced Concurrency & Stress Tests:
```bash
# Run the stress test suite
pytest SDK/tests/test_concurrency_stress.py -v

# Run the benchmark visualizer & report generator
python scripts/run_stress_benchmark_suite.py
```

Results are saved to `test_results/benchmark_report.json` and `test_results/concurrency_stress_benchmark.png`.

---

## 9. Troubleshooting & FAQ

| Issue | Diagnosis | Solution |
| :--- | :--- | :--- |
| `Bootstrap key rejected` | Server rejected handshake | Ensure `VIENTO_BOOTSTRAP_KEY` matches between client and cloud. |
| `Queue full (max 50)` | Node reached max queue depth | Increase `--concurrency` or add more worker nodes to the mesh. |
| `Model not found` | Requested model not loaded | Run `viento models` to inspect loaded weights, or `ollama pull <model>`. |
| `nvidia-smi not found` | Running on CPU-only node | Normal behavior; Viento gracefully falls back to CPU & RAM telemetry. |
