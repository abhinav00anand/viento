# ⚡ Zephyr Distributed Edge Inference Mesh

<div align="center">

```text
  ███████╗███████╗██████╗ ██╗  ██╗██╗   ██╗██████╗ 
  ╚══███╔╝██╔════╝██╔══██╗██║  ██║╚██╗ ██╔╝██╔══██╗
    ███╔╝ █████╗  ██████╔╝███████║ ╚████╔╝ ██████╔╝
   ███╔╝  ██╔══╝  ██╔═══╝ ██╔══██║  ╚██╔╝  ██╔══██╗
  ███████╗███████╗██║     ██║  ██║   ██║   ██║  ██║
  ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
```

**Zero-Trust Distributed Inference Network · Edge-to-Cloud · OpenAI-Compatible**

[![PyPI version](https://img.shields.io/badge/pypi-v0.1.0-blue.svg?style=for-the-badge&logo=pypi)](https://pypi.org/project/viento/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA%20Accelerated-EE4C2C.svg?style=for-the-badge&logo=pytorch)](https://pytorch.org)
[![Tests Passing](https://img.shields.io/badge/tests-71%20passed-success.svg?style=for-the-badge&logo=pytest)](Cloud/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

[Architecture](#-system-architecture) • [Step-by-Step Run Guide](#-step-by-step-how-to-run--what-to-run) • [Cloud GPU (Lightning AI T4)](#-cloud-gpu-validation-lightning-ai-tesla-t4) • [CLI Reference](#-cli-command-reference) • [Protocol Specs](#-protocol--security-architecture)

</div>

---

## 🌐 What is Zephyr?

**Zephyr** is a high-performance, zero-trust distributed inference mesh. It connects consumer edge hardware and cloud GPU instances running local inference engines ([Ollama](https://ollama.ai), [vLLM](https://github.com/vllm-project/vllm), [llama.cpp](https://github.com/ggerganov/llama.cpp), or HuggingFace) to a centralized Cloud Control Plane Gateway.

Once an edge or cloud node connects via an outbound, encrypted WebSocket (`/ws/runtime`), it is securely assigned a session-scoped API key. Any standard OpenAI client, library, or frontend app can query your private GPU nodes over HTTPS from anywhere in the world—**without port forwarding, static IPs, or exposing your local network**.

---

## 🏗 System Architecture

```mermaid
flowchart TD
    subgraph Clients["Users & Applications"]
        C1["OpenAI SDK / Python"]
        C2["cURL / HTTP Clients"]
        C3["Web UIs & Chatbots"]
    end

    subgraph CloudGW["Zephyr Cloud Control Plane (FastAPI / Uvicorn)"]
        REST["REST API Layer<br/>POST /v1/chat/completions<br/>POST /v1/embeddings<br/>GET /v1/models"]
        AUTH["Zero-Trust Scoped KeyStore<br/>(SHA-256 Hashed · 1-Hour TTL)"]
        DISP["Atomic Multi-Tier Dispatcher<br/>(Concurrency Guard & Backpressure)"]
        WSS_GW["Outbound WebSocket Gateway<br/>/ws/runtime"]
    end

    subgraph Workers["Edge & Cloud GPU Runtime Nodes (Viento SDK)"]
        direction TB
        subgraph Node1["Local Edge Rig"]
            N1["Viento Runtime Worker"]
            OL["Ollama Engine<br/>(llama3:8b, mistral:7b)"]
        end
        subgraph Node2["Cloud GPU Worker (e.g. Lightning AI T4)"]
            N2["Viento Runtime Worker"]
            T4["Tesla T4 GPU (16GB VRAM)<br/>(Qwen2.5-0.5B, vLLM)"]
        end
    end

    C1 & C2 & C3 -->|"HTTPS Requests with zph_tmp_..."| REST
    REST --> AUTH
    AUTH --> DISP
    DISP <==>|"Pydantic V2 Envelope Protocol (WSS)"| WSS_GW
    WSS_GW <===>|"Secure Bidirectional Tunnel"| N1
    WSS_GW <===>|"Secure Bidirectional Tunnel"| N2
    N1 --> OL
    N2 --> T4
```

---

## 🚀 Step-by-Step: How to Run & What to Run

Follow this clear, step-by-step guide to run the entire Zephyr mesh locally or across cloud instances.

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           EXECUTION ROADMAP                               │
│                                                                           │
│  [Step 1] Clone Repo & Prepare Virtual Environment                        │
│      ↓                                                                    │
│  [Step 2] Start Cloud Control Plane Server (Port 10000)                   │
│      ↓                                                                    │
│  [Step 3] Boot Inference Engine (Ollama / HuggingFace / vLLM)             │
│      ↓                                                                    │
│  [Step 4] Run Edge Runtime Worker (`viento run`)                          │
│      ↓                                                                    │
│  [Step 5] Send Inference Requests via OpenAI-Compatible API              │
└───────────────────────────────────────────────────────────────────────────┘
```

---

### Step 1: Clone Repository & Create Virtual Environment

Open your terminal and clone the repository:

```bash
git clone https://github.com/abhinav00anand/zephyr.git
cd zephyr

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux / macOS:
source venv/bin/activate
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
```

---

### Step 2: Start the Cloud Control Plane

The Cloud Control Plane orchestrates active runtime sessions, mints temporary keys, and routes incoming REST requests to connected nodes.

```bash
cd Cloud
pip install -r requirements.txt

# Set deployment configuration
export ZEPHYR_ENV=development
export ZEPHYR_BOOTSTRAP_KEY=zephyr_dev_secret_key_2026
export ZEPHYR_PORT=10000

# On Windows PowerShell:
# $env:ZEPHYR_ENV="development"
# $env:ZEPHYR_BOOTSTRAP_KEY="zephyr_dev_secret_key_2026"
# $env:ZEPHYR_PORT="10000"

# Launch server with single-worker in-memory state
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```

#### What You Will See:
```text
INFO:     Started server process [14820]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:10000 (Press CTRL+C to quit)
```

> **Interactive Documentation**:
> - Swagger UI: `http://localhost:10000/docs`
> - Health Check: `http://localhost:10000/healthz`

---

### Step 3: Start Your Inference Backend

Zephyr supports **Ollama**, **vLLM**, **llama.cpp**, or native Python HuggingFace models.

#### Option A: Ollama (Recommended for Local PCs & Desktops)
Download and install [Ollama](https://ollama.ai), then start the daemon and pull a model:
```bash
# In a new terminal:
ollama serve

# Pull desired model weights
ollama pull llama3:latest
# or
ollama pull phi3:mini
```

#### Option B: HuggingFace / Transformers / GPU
If running on a cloud GPU (e.g. T4 / A100), you can run models directly with PyTorch or vLLM:
```bash
pip install transformers accelerate torch
```

---

### Step 4: Boot the Edge Runtime Node (`viento run`)

The `viento` SDK automatically discovers your local models, GPU/CPU telemetry, and establishes a secure tunnel with the Cloud Gateway.

In a new terminal window:
```bash
# Install the Viento SDK
pip install -e SDK/

# Set the bootstrap secret matching the cloud server
export ZEPHYR_BOOTSTRAP_KEY=zephyr_dev_secret_key_2026

# Connect to the local Cloud Server
viento run --server ws://localhost:10000/ws/runtime

# (Or connect to the production cloud gateway)
# viento run --server wss://viento.onrender.com/ws/runtime
```

#### Expected Terminal Output:
```text
╔══════════════════════════════════════════════════════════════╗
║               ⚡  ZEPHYR NODE AUTHENTICATED  ⚡              ║
╠══════════════════════════════════════════════════════════════╣
║  Session ID  : zph_sess_7a3d12c8                            ║
║  API Key     : zph_tmp_9e8f1b2c4d5a... (1-hour TTL)         ║
║  Models      : llama3:latest, phi3:mini                     ║
║  Backend     : Ollama @ http://localhost:11434               ║
║  Capacity    : Max 2 concurrent jobs                         ║
║  Status      : 🟢 Online — awaiting mesh jobs               ║
╚══════════════════════════════════════════════════════════════╝
```

> 🔑 **Copy the temporary API key (`zph_tmp_...`)** printed in the box! This key gives instant access to your connected node through the cloud REST API.

---

### Step 5: Send Inference Requests (OpenAI-Compatible API)

You can now hit the cloud gateway using standard `curl` or any OpenAI SDK client.

#### Using cURL (Streaming):
```bash
curl -N http://localhost:10000/v1/chat/completions \
  -H "Authorization: Bearer zph_tmp_YOUR_SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3:latest",
    "messages": [
      {"role": "system", "content": "You are a distributed inference assistant."},
      {"role": "user", "content": "Explain quantum computing in two sentences."}
    ],
    "stream": true,
    "temperature": 0.7
  }'
```

#### Using Python OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:10000/v1",
    api_key="zph_tmp_YOUR_SESSION_KEY"
)

response = client.chat.completions.create(
    model="llama3:latest",
    messages=[
        {"role": "user", "content": "Write a haiku about distributed AI."}
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

## ⚡ Cloud GPU Validation: Lightning AI Tesla T4

Zephyr has been tested and verified on a live **Lightning AI Studio** powered by an **NVIDIA Tesla T4 GPU (16 GB GDDR6 VRAM)**.

### Visual Validation & Telemetry

<div align="center">

![Zephyr Lightning AI T4 Live Execution](assets/lightning_t4_execution.gif)

<br/>

![Zephyr Lightning AI T4 GPU Benchmark](assets/lightning_t4_gpu_test.png)

</div>

### Hardware & Benchmark Results

| Metric | Measured Value | Details / Benchmark Spec |
| :--- | :--- | :--- |
| **Cloud GPU** | **NVIDIA Tesla T4** | 16GB GDDR6 · Compute Capability 7.5 |
| **CUDA Environment** | **CUDA 12.8 / 13.0** | NVIDIA-SMI Driver 580.173.02 · PyTorch 2.8.0+cu128 |
| **FP16 Tensor Cores** | **24.19 TFLOPS** | 5.68 ms/iter (4096 × 4096 FP16 GEMM) |
| **Model Ingested** | `Qwen/Qwen2.5-0.5B` | Loaded to `cuda:0` in 1.67 seconds |
| **VRAM Footprint** | **1,047.9 MB** | Only 7% of available 16GB VRAM utilized |
| **Inference Speed** | **28.05 tokens/sec** | Real-time chat completion on Tesla T4 |
| **SDK Test Suite** | **71 / 71 PASSED** | 100% test pass rate in 4.11 seconds |

### Running Zephyr on Lightning AI Cloud GPU

You can run your own cloud node on Lightning AI programmatically using `lightning-sdk`:

```python
from lightning_sdk.lightning_cloud.login import Auth
from lightning_sdk import Studio, Machine

# 1. Authenticate with your Lightning AI API Key
auth = Auth()
auth.save(user_id="YOUR_USER_ID", auth_token="sk-lit-YOUR_KEY")

# 2. Initialize and start Studio on Tesla T4 GPU
studio = Studio(
    name="zephyr-t4-node",
    teamspace="YOUR_TEAMSPACE",
    user="YOUR_USERNAME",
    create_ok=True
)
studio.start(machine=Machine.T4)

# 3. Clone and execute tests inside the T4 GPU environment
print(studio.run("nvidia-smi"))
print(studio.run("""
git clone https://github.com/abhinav00anand/zephyr.git
cd zephyr
pip install -q -e . pytest
pytest tests/ -v
"""))

# 4. Stop Studio when done to conserve credits
studio.stop()
```

---

## 🛠 CLI Command Reference (`viento`)

| Command | Description | Example |
| :--- | :--- | :--- |
| `viento run` | Starts the worker node and attaches to mesh | `viento run --server wss://viento.onrender.com/ws/runtime` |
| `viento run --concurrency <N>` | Sets maximum parallel inference slots | `viento run --concurrency 4` |
| `viento models` | Lists all models discovered on local backends | `viento models` |
| `viento pull <model>` | Pulls weights via Ollama adapter | `viento pull llama3:latest` |
| `viento doctor` | Comprehensive diagnostic check (GPU, RAM, ports) | `viento doctor` |
| `viento status` | Displays active session ID, key TTL, and metrics | `viento status` |
| `viento config view` | Shows current configuration parameters | `viento config view` |
| `viento config set <k> <v>` | Updates a configuration property | `viento config set server.port 10000` |
| `viento stop` | Gracefully drains running jobs and disconnects | `viento stop` |

---

## 🛡 Protocol & Security Architecture

1. **Strict Canonical Envelope Protocol (V1.0)**:
   - Every WebSocket frame adheres to strict Pydantic V2 schema validation (`extra="forbid"`).
   - Directional monotonic sequence numbers prevent replay attacks and detect dropped frames.
2. **Zero-Trust Scoped Keys**:
   - WebSocket handshakes enforce `ZEPHYR_BOOTSTRAP_KEY` validation during `HELLO`.
   - Node registration automatically mints a temporary 1-hour token (`zph_tmp_<48 hex chars>`) SHA-256 hashed at rest.
   - Disconnecting or terminating the WebSocket immediately revokes the associated token.
3. **Atomic Multi-Tier Capacity Control**:
   - Strict hierarchical checks: `Session Alive` → `Model Ready` → `Model Concurrency Limit` → `Session Concurrency Limit` → `Queue Depth`.
   - Atomic terminalization guard (`_terminal_jobs`) guarantees job counters decrement **EXACTLY ONCE**.
4. **Immediate TCP Socket Stream Cancellation**:
   - Cancelling an active inference stream triggers `ExecutionHandle.cancel()`, closing the backend socket instantly without leaving orphan generation threads consuming GPU compute.
5. **Zero Token Drop Backpressure**:
   - Async queue streams enforce timeout-bounded backpressure (`asyncio.wait_for(queue.put(), timeout=5.0)`). Tokens are never silently lost.

---

## 🧪 Running Automated Tests

Run the test suite locally or in CI:

```bash
# 1. Run Cloud Server test suite
pytest Cloud/tests/ -v

# 2. Run SDK test suite
pytest SDK/tests/ -v

# 3. Run full protocol schema verification
python scripts/generate_protocol_schema.py

# 4. Run security threat model auditor
python Private/research/threat_model.py
```

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
