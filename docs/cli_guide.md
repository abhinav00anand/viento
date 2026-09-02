# Viento CLI Complete User Guide & Reference

The `viento` command-line interface provides comprehensive control over local node execution, model registration, diagnostics, configuration, and job scheduling for the Viento AI mesh.

---

## Command Reference Summary

| Command | Summary | Key Options |
|---|---|---|
| `viento run` | Boots runtime, connects WSS, handshakes, issues 1-hr key, enters job loop | `--server`, `--ollama-url`, `--concurrency` |
| `viento status` | Inspects local state, active session ID, key TTL, and metrics | None |
| `viento models` | Lists local models discovered from Ollama | None |
| `viento doctor` | Runs health diagnostics on Ollama, hardware, and network | None |
| `viento config` | Views (`view`) or edits (`get`, `set`) local `config.toml` | `view`, `get KEY`, `set KEY VALUE` |
| `viento pull` | Pulls LLM model weights from Ollama registry with progress bar | `<model_name>` |
| `viento stop` | Gracefully drains active jobs, sends disconnect frame, and exits | None |

---

## Detailed Command Documentation

### 1. `viento run`

Boots the local runtime node. Auto-discovers locally installed models via Ollama (`http://localhost:11434/api/tags`), opens an outbound WebSocket connection to the Viento Cloud Gateway, sends a handshake frame, and receives a temporary 1-hour session API key (`vnt_tmp_...`).

#### Usage:
```bash
viento run [OPTIONS]
```

#### Options:
- `-s, --server TEXT`: Override default WSS gateway URL (`wss://viento.onrender.com/ws/runtime`).
- `-o, --ollama-url TEXT`: Override default Ollama API endpoint (`http://localhost:11434`).
- `-c, --concurrency INTEGER`: Set maximum concurrent inference jobs (default: `1`).

#### Examples:
```bash
# Standard boot
viento run

# Connect to local dev server with concurrency 2
viento run --server wss://localhost:8000/ws/runtime --concurrency 2
```

---

### 2. `viento status`

Displays node status panel showing:
- Current state (`RUNNING`, `BUSY`, `BOOTING`, `RECONNECTING`, `STOPPED`)
- Active Session ID
- Active temporary API Key & remaining TTL (Time-To-Live in minutes/seconds)
- Configured endpoints
- List of registered models
- Cumulative jobs completed and failed
- Total node uptime

#### Usage:
```bash
viento status
```

---

### 3. `viento doctor`

Performs an automated environment diagnostic scan:
1. **Ollama Reachability**: Queries `http://localhost:11434/api/tags` and reports model count.
2. **CPU & RAM**: Measures active CPU load % and available system memory.
3. **GPU Diagnostics**: Detects NVIDIA GPUs, VRAM utilization, and PyNVML driver state.
4. **Cloud Network**: Tests HTTP GET reachability against Viento Cloud `/health`.

#### Usage:
```bash
viento doctor
```

---

### 4. `viento models`

Prints a formatted table of all LLM models currently installed in the local Ollama instance, detailing model name, total file size on disk (GB), model architecture family, quantization level (e.g. `Q4_K_M`), and last modified date.

#### Usage:
```bash
viento models
```

---

### 5. `viento config`

Manage local configuration stored in `~/.viento/config.toml`.

#### Subcommands:

##### View configuration file:
```bash
viento config view
```

##### Read single value:
```bash
viento config get max_concurrency
```

##### Set configuration value:
```bash
viento config set max_concurrency 2
viento config set server_url wss://gateway.viento.cloud/ws/runtime
```

---

### 6. `viento pull <model>`

Interacts with local Ollama service to download model weights from the registry while rendering real-time progress bars for each model layer.

#### Usage:
```bash
viento pull <model_name>
```

#### Example:
```bash
viento pull llama3:latest
```

---

### 7. `viento stop`

Gracefully halts the running node by draining any pending jobs in the queue, sending a `disconnect` frame to the cloud gateway, clearing active session state, and returning the node status to `STOPPED`.

#### Usage:
```bash
viento stop
```

---

## File System Locations

- Configuration: `~/.viento/config.toml`
- Runtime Session State: `~/.viento/runtime.json`
- Log Files: `~/.viento/logs/`
