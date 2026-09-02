"""
Configuration Loader and Directory Manager for Viento SDK.

Manages ~/.viento/config.toml, ~/.viento/runtime.json, and log directories.
Secrets (like bootstrap_key) are read dynamically from environment variables
and are NEVER written to disk in plain text.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# BUG-7 FIX: tomllib is stdlib only in Python 3.11+; fall back to tomli on 3.9/3.10
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

try:
    import tomli_w
except ImportError:
    tomli_w = None

logger = logging.getLogger("viento.config")


def get_default_node_name() -> str:
    """Generate a machine-unique node name using hostname + short UUID fragment."""
    import socket
    import uuid

    hostname = socket.gethostname().split(".")[0].lower().replace("_", "-")[:12]
    uid = uuid.uuid4().hex[:6]
    return f"viento-node-{hostname}-{uid}"


@dataclass
class VientoConfig:
    server_url: str = "wss://viento.onrender.com/ws/runtime"
    cloud_api_url: str = "https://viento.onrender.com"
    http_url: str = "https://viento.onrender.com"
    model_backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    vllm_url: str = "http://localhost:8000/v1"
    llamacpp_url: str = "http://localhost:8080"
    # BUG-10 FIX: default node_name is now machine-unique via get_default_node_name()
    node_name: str = field(default_factory=get_default_node_name)
    bootstrap_key: str = ""
    max_concurrency: int = 2
    max_queue_depth: int = 50
    heartbeat_interval: float = 15.0
    heartbeat_deadline: float = 45.0
    job_timeout: float = 120.0
    token_ttl: float = 3600.0
    log_level: str = "INFO"
    log_json: bool = False
    reconnect_base_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    reconnect_jitter_factor: float = 0.2

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VientoConfig":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary excluding any secret fields."""
        d = asdict(self)
        d.pop("bootstrap_key", None)
        return d


@dataclass
class RuntimeState:
    session_id: Optional[str] = None
    runtime_id: Optional[str] = None
    last_registered_at: Optional[float] = None
    active_key: Optional[str] = None
    key_expires_at: Optional[float] = None
    registered_models: List[str] = field(default_factory=list)
    status: str = "stopped"
    uptime_start: Optional[float] = None
    last_heartbeat: Optional[float] = None
    # BUG-4 FIX: Added missing fields referenced by CLI status_command
    jobs_completed: int = 0
    jobs_failed: int = 0
    pid: Optional[int] = None
    process_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("active_key", None)  # Strips sensitive active API key before disk save
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeState":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class ConfigManager:
    """Manages reading and persisting configuration to ~/.viento/ directory."""

    def __init__(self, base_dir: Optional[Path] = None, viento_dir: Optional[Path] = None):
        self.base_dir = base_dir or viento_dir or (Path.home() / ".viento")
        self.config_path = self.base_dir / "config.toml"
        self.runtime_state_path = self.base_dir / "runtime.json"
        self.log_dir = self.base_dir / "logs"
        self._ensure_directories()

    # BUG-3 FIX: Add property aliases that CLI code uses
    @property
    def config_file(self) -> Path:
        """Alias for config_path used by CLI commands."""
        return self.config_path

    @property
    def logs_dir(self) -> Path:
        """Alias for log_dir used by CLI commands."""
        return self.log_dir

    @property
    def viento_dir(self) -> Path:
        """Alias for base_dir used by CLI commands."""
        return self.base_dir

    def ensure_directories(self) -> None:
        """Public alias for _ensure_directories used by CLI init command."""
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> VientoConfig:
        """Load config from disk if exists, otherwise return defaults."""
        if not self.config_path.exists():
            config = VientoConfig()
            self.save_config(config)
            return config

        if tomllib is None:
            logger.warning("Neither tomllib nor tomli available. Using defaults.")
            return VientoConfig()

        try:
            with open(self.config_path, "rb") as f:
                data = tomllib.load(f)
            return VientoConfig.from_dict(data)
        except Exception as exc:
            logger.error("Failed to parse %s: %s. Using defaults.", self.config_path, exc)
            return VientoConfig()

    def save_config(self, config: VientoConfig) -> None:
        """Save configuration to ~/.viento/config.toml safely without secrets."""
        try:
            d = config.to_dict()
            if tomli_w:
                with open(self.config_path, "wb") as f:
                    tomli_w.dump(d, f)
            else:
                lines = [
                    f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}" for k, v in d.items()
                ]
                self.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            logger.info("Saved configuration to %s", self.config_path)
        except Exception as exc:
            logger.error("Failed to save config to %s: %s", self.config_path, exc)

    def load_runtime_state(self) -> RuntimeState:
        if not self.runtime_state_path.exists():
            return RuntimeState()
        try:
            with open(self.runtime_state_path, encoding="utf-8") as f:
                data = json.load(f)
            return RuntimeState.from_dict(data)
        except Exception:
            return RuntimeState()

    def save_runtime_state(self, state: RuntimeState) -> None:
        try:
            with open(self.runtime_state_path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error("Failed to save runtime state: %s", exc)

    def update_runtime_state(self, **kwargs) -> None:
        """Load the runtime state from disk, update specified fields, and save back to disk."""
        state = self.load_runtime_state()
        for k, v in kwargs.items():
            if k == "active_api_key":
                state.active_key = v
            elif hasattr(state, k):
                setattr(state, k, v)
        self.save_runtime_state(state)

    def get_active_key_ttl(self) -> float:
        """Return remaining TTL seconds for the active API key, or 0.0 if expired/none."""
        state = self.load_runtime_state()
        if state.key_expires_at is None:
            return 0.0
        import time

        remaining = state.key_expires_at - time.time()
        return max(0.0, remaining)

    def get_bootstrap_key(self) -> str:
        """Get bootstrap key strictly from environment variable."""
        return os.getenv("VIENTO_BOOTSTRAP_KEY", "")
