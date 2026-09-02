# 🚀 How to Run Viento & Viento SDK: Complete Step-by-Step Guide

Welcome to the operator and execution guide for **Viento & Viento**. This document explains exactly what to run and how to run each component, step by step.

---

## 🌐 Live Mesh Network Endpoints

Viento is deployed and running live on the cloud:

| Component | Live Production URL | Purpose |
| :--- | :--- | :--- |
| **OpenAI Chat Endpoint** | `POST https://viento.onrender.com/v1/chat/completions` | Direct HTTP / cURL chat completion endpoint |
| **SDK Base URL** | `https://viento.onrender.com/v1` | `base_url` for OpenAI Python/Node SDKs |
| **Models Discovery** | `GET https://viento.onrender.com/v1/models` | List active models across all connected mesh nodes |
| **Interactive Docs** | `https://viento.onrender.com/docs` | Swagger UI for exploring and testing API endpoints |
| **Health Probe** | `https://viento.onrender.com/healthz` | Cluster status & count of connected runtime nodes |
| **WebSocket Mesh Tunnel** | `wss://viento.onrender.com/ws/runtime` | Endpoint that local & cloud GPU worker nodes connect to |

---

## ⚡ Quickstart: Connect an Edge Node in 3 Steps

If you want to contribute compute (local GPU, CPU, or cloud instance) to the live Viento mesh:

### Step 1: Install Viento SDK
```bash
# Clone the repository
git clone https://github.com/abhinav00anand/viento.git
cd viento

# Install the lightweight SDK in editable mode
pip install -e SDK/
```

Verify installation:
```bash
viento --help
```

---

### Step 2: Start Your Local Inference Engine

Viento's lightweight architecture works with any existing inference engine:

#### Option A: Ollama (Easiest for Local Workstations & Laptops)
1. Install from [ollama.ai](https://ollama.ai) and start:
   ```bash
   ollama serve
   ```
2. Pull your favorite model:
   ```bash
   ollama pull llama3:latest
   # or small models for fast testing:
   ollama pull phi3:mini
   ollama pull qwen2.5:0.5b
   ```

#### Option B: vLLM (High Throughput for NVIDIA GPUs)
```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-0.5B-Instruct \
    --port 8000 \
    --dtype float16
```

#### Option C: llama.cpp Server
```bash
./llama-server -m models/llama-3-8b-instruct.Q4_K_M.gguf --port 8080
```

---

### Step 3: Run the Edge Worker Node

Connect your node to the live production mesh at `viento.onrender.com`:

```bash
# Export the cluster bootstrap key (contact cluster admin or use your configured secret)
export VIENTO_BOOTSTRAP_KEY=viento_dev_secret_key_2026

# Connect to the live mesh
viento run --server wss://viento.onrender.com/ws/runtime
```

*(On Windows PowerShell)*:
```powershell
$env:VIENTO_BOOTSTRAP_KEY="viento_dev_secret_key_2026"
viento run --server wss://viento.onrender.com/ws/runtime
```

Upon connection, Viento discovers your local models and prints your session banner:
```text
╔══════════════════════════════════════════════════════════════╗
║               ⚡  VIENTO NODE AUTHENTICATED  ⚡              ║
╠══════════════════════════════════════════════════════════════╣
║  Session ID  : vnt_sess_7a3d12c8                            ║
║  API Key     : vnt_tmp_9e8f1b2c4d5a... (1-hour TTL)         ║
║  Models      : llama3:latest, qwen2.5:0.5b                  ║
║  Gateway     : wss://viento.onrender.com/ws/runtime          ║
║  Status      : 🟢 Online — ready for streaming inference    ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 📡 Querying the Live Mesh (OpenAI Compatible)

Once your worker is connected, anyone with your session key (or cluster API key) can send inference queries through `https://viento.onrender.com/v1`:

### 1. Python OpenAI SDK
```python
from openai import OpenAI

# Point client directly to the live Viento gateway
client = OpenAI(
    base_url="https://viento.onrender.com/v1",
    api_key="vnt_tmp_YOUR_SESSION_KEY"  # Or your cluster API key
)

# Stream tokens in real-time
stream = client.chat.completions.create(
    model="llama3:latest",
    messages=[
        {"role": "system", "content": "You are a concise, helpful AI assistant."},
        {"role": "user", "content": "Explain quantum computing in 2 sentences."}
    ],
    stream=True,
    temperature=0.7
)

for chunk in stream:
    token = chunk.choices[0].delta.content
    if token:
        print(token, end="", flush=True)
print()
```

### 2. cURL (Streaming Server-Sent Events)
```bash
curl -N https://viento.onrender.com/v1/chat/completions \
  -H "Authorization: Bearer vnt_tmp_YOUR_SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3:latest",
    "messages": [
      {"role": "user", "content": "Why is the sky blue?"}
    ],
    "stream": true
  }'
```

### 3. List Available Models Across the Mesh
```bash
curl https://viento.onrender.com/v1/models \
  -H "Authorization: Bearer vnt_tmp_YOUR_SESSION_KEY"
```

---

## ☁️ Running on Cloud GPUs (Lightning AI / Kaggle / Colab)

You can run worker nodes on free or low-cost cloud GPUs in just a few minutes.

### ⚡ Lightning AI (NVIDIA Tesla T4 / L4)

1. Save your credentials in `~/.lightning/credentials.json`:
   ```json
   {
     "auth_token": "sk-lit-YOUR_KEY",
     "user_id": "YOUR_USER_ID"
   }
   ```

2. Run the automated deployment script:
   ```bash
   python scripts/run_gpu_inference_benchmark.py
   ```

3. Or launch manually from inside your Lightning Studio terminal:
   ```bash
   git clone https://github.com/abhinav00anand/viento.git
   cd viento
   pip install -e SDK/
   export VIENTO_BOOTSTRAP_KEY=viento_dev_secret_key_2026
   viento run --server wss://viento.onrender.com/ws/runtime
   ```

### 📓 Kaggle Notebook (Free 2x Tesla T4 GPUs)
In a Kaggle Python notebook with GPU enabled:
```python
!git clone https://github.com/abhinav00anand/viento.git
%cd viento
!pip install -q -e SDK/

# Launch background node
import subprocess
import os

env = os.environ.copy()
env["VIENTO_BOOTSTRAP_KEY"] = "viento_dev_secret_key_2026"

proc = subprocess.Popen(
    ["viento", "run", "--server", "wss://viento.onrender.com/ws/runtime"],
    env=env
)
print("Viento worker launched on Kaggle GPU!")
```

---

## 🏢 Self-Hosting the Cloud Gateway (Optional)

If you wish to run your own private cloud gateway rather than using `viento.onrender.com`:

```bash
cd Cloud
pip install -r requirements.txt

# Configure settings
export VIENTO_ENV=development
export VIENTO_BOOTSTRAP_KEY=my_custom_secret_key
export VIENTO_PORT=10000

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```

Your private gateway is now available at:
- Gateway: `http://localhost:10000`
- WebSockets: `ws://localhost:10000/ws/runtime`
- Docs: `http://localhost:10000/docs`

---

## 🧪 Running Diagnostic Tools & Test Suites

### Health Diagnostics
Check local environment and inference engine connectivity:
```bash
viento doctor
```

### Check Hardware & Mesh Status
```bash
viento status
```

### Run Unit & Integration Test Suites
```bash
# Full test suite (79/79 passing)
pytest SDK/tests -v
```

### Run Advanced Concurrency Stress Tests & Benchmarks
```bash
# Concurrency stress tests
pytest SDK/tests/test_concurrency_stress.py -v

# Generate benchmark visual report (saved to test_results/)
python scripts/run_stress_benchmark_suite.py
```

---

## 🛠️ CLI Reference Table (`viento`)

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `viento run` | `--server <url>` | Connects node to WebSocket gateway and listens for jobs |
| `viento run` | `--backend <ollama\|vllm>` | Specifies inference backend (default: `ollama`) |
| `viento run` | `--concurrency <N>` | Maximum parallel generation jobs (default: 2) |
| `viento doctor` | None | Validates backend reachability and model availability |
| `viento models` | None | Discovers and prints all locally loaded models |
| `viento status` | None | Displays CPU, RAM, and GPU telemetry |
| `viento config` | `--set key=val` | Modifies persistent configuration |
