# 🚀 Quickstart Guide

Get up and running with a distributed Viento node in under 2 minutes.

---

## 1. Prerequisites

- Python 3.9+
- A running local or remote inference engine:
  - [Ollama](https://ollama.com) (default)
  - [vLLM](https://docs.vllm.ai)
  - [llama.cpp](https://github.com/ggerganov/llama.cpp)

---

## 2. Installation

Install via `pip`:

```bash
pip install -U viento
```

Verify installation:

```bash
viento version
```

---

## 3. Start Local Engine

If using Ollama, pull and start a model:

```bash
ollama run llama3:latest
```

---

## 4. Run Doctor Diagnostic

Validate local engine reachability and discovered models:

```bash
viento doctor
```

---

## 5. Connect Node to Mesh

Launch the runtime node and establish an outbound WebSocket tunnel to the cloud gateway:

```bash
export VIENTO_BOOTSTRAP_KEY=<your-bootstrap-key>
viento run --server wss://viento.onrender.com/ws/runtime
```

On successful boot, the node completes authentication and displays:

- Active Session ID
- Temporary 1-hour Client API Key (`vnt_tmp_...`)
- Discovered local models

---

## 6. Query the Mesh

Use any OpenAI-compatible client library or `curl` to send inference requests:

```bash
curl https://viento.onrender.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-session-api-key>" \
  -d '{
    "model": "llama3:latest",
    "messages": [{"role": "user", "content": "Hello, Viento!"}],
    "stream": true
  }'
```
