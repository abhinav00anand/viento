# Viento SDK - Ollama Deep Integration & Optimization Guide

This document provides complete instructions for pairing the **Viento SDK** (`viento`) with [Ollama](https://ollama.com) as your primary local inference backend.

---

## Architecture Blueprint

```
 ┌─────────────────────────────────────────────────────────┐
 │                   Model Host Machine                    │
 │                                                         │
 │  ┌─────────────────────────┐   HTTP   ┌──────────────┐  │
 │  │ Viento SDK CLI          │ ─────────│ Ollama API   │  │
 │  │ (viento run)            │ localhost│ :11434       │  │
 │  └────────────┬────────────┘ :11434   └──────────────┘  │
 └───────────────┼─────────────────────────────────────────┘
                 │ Outbound WSS /ws/runtime
                 ▼
      [ Viento Cloud Server ]
   (https://viento.onrender.com)
```

---

## Ollama Prerequisites & Installation

Ensure Ollama is installed and active on your system:

### Linux / macOS
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

### Windows
Download the Windows installer from [ollama.com/download](https://ollama.com/download) and run the setup executable.

Verify Ollama service reachability:
```bash
curl http://localhost:11434/api/tags
```

---

## Supported Ollama Models

Viento automatically discovers all models pulled locally into your Ollama instance:

| Model Tag | Parameters | Recommended Quantization | Memory (VRAM) |
|---|---|---|---|
| `llama3.1:8b` | 8 Billion | `q4_k_m` | 5.2 GB |
| `qwen2.5:7b` | 7 Billion | `q4_k_m` | 4.8 GB |
| `mistral:7b` | 7 Billion | `q4_k_m` | 4.5 GB |
| `gemma2:9b` | 9 Billion | `q4_k_m` | 6.1 GB |
| `nomic-embed-text` | 137 Million | `fp16` | 0.5 GB |

---

## Operating Viento with Ollama

### 1. Model Discovery & Verification
Before booting the cloud runtime, verify available models:

```bash
viento models
```

### 2. Pulling New Models Interactive
Pull new model weights directly via Viento CLI:

```bash
viento pull llama3.1:8b
```

### 3. Starting the Node Session
Boot the Viento runtime bound to Ollama:

```bash
viento run --backend ollama --server https://viento.onrender.com
```

Output:
```text
┌─────────────────────────────────────────────────────────────┐
│                 VIENTO LOCAL RUNTIME ONLINE                 │
│                                                             │
│  Server Target : https://viento.onrender.com               │
│  Backend Engine: Ollama (http://localhost:11434)           │
│  Discovered    : llama3.1:8b, qwen2.5:7b                    │
│                                                             │
│  Temporary Key : vnt_tmp_9f8c2b7d4a1e3f608152438761109abc    │
│  Key Expiry    : 1 Hour (3600 seconds)                      │
│                                                             │
│  Use this key in standard OpenAI SDK applications!          │
└─────────────────────────────────────────────────────────────┘
```

---

## Advanced Ollama Adapter Tuning

You can tune context window size (`num_ctx`), temperature, GPU acceleration, and max concurrency in `~/.viento/config.toml`:

```toml
[backend]
type = "ollama"
url = "http://127.0.0.1:11434"

[backend.options]
num_ctx = 8192
num_thread = 8
temperature = 0.7

[runtime]
max_concurrency = 2
heartbeat_interval_seconds = 15
```

---

## Troubleshooting

### Error: `Ollama service unreachable`
- Run `viento doctor` to diagnose connection bottlenecks.
- Check if Ollama is running (`ps aux | grep ollama` or system service manager).
- Check environment variable `OLLAMA_HOST` if binding on custom IP addresses.
