"""
Configuration Loader and Directory Manager for Viento SDK.

Manages ~/.viento/config.toml, ~/.viento/runtime.json, and log directories.
Secrets (like bootstrap_key) are read dynamically from environment variables
and are NEVER written to disk in plain text.
"""

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import tomllib

try:
    import tomli_w
except ImportError:
    import socket
import uuid

logger = logging.getLogger("viento.config")


def get_default_node_name() -> str:
    """Generate a unique node identifier per machine/container instance."""
    try:
        host = socket.gethostname()
        host_clean = "".join(c for c in host if c.isalnum() or c in ("-", "_")).lower()
        if host_clean and host_clean not in ("localhost", "127.0.0.1"):
            # Include a 4-char random hash to distinguish multiple colab/docker instances on same host type
            return f"viento-node-{host_clean[:10]}-{uuid.uuid4().hex[:4]}"
    except Exception:
        pass
    return f"viento-node-{uuid.uuid4().hex[:6]}"


@dataclass
class VientoConfig:
    server_url: str = "wss://viento.onrender.com/ws/runtime"
    cloud_api_url: str = "https://viento.onrender.com"
    http_url: str = "https://viento.onrender.com"
    model_backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    vllm_url: str = "http://localhost:8000/v1"
    llamacpp_url: str = "http://localhost:8080"
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
    status: Optional[str] = None
    uptime_start: Optional[float] = None
    last_heartbeat: Optional[float] = None

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

    def _ensure_directories(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> VientoConfig:
        """Load config from disk if exists, otherwise return defaults."""
        if not self.config_path.exists():
            config = VientoConfig()
            self.save_config(config)
            return config

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
                lines = [f'{k} = "{v}"' if isinstance(v, str) else f'{k} = {v}' for k, v in d.items()]
                self.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            logger.info("Saved configuration to %s", self.config_path)
        except Exception as exc:
            logger.error("Failed to save config to %s: %s", self.config_path, exc)

    def load_runtime_state(self) -> RuntimeState:
        if not self.runtime_state_path.exists():
            return RuntimeState()
        try:
            with open(self.runtime_state_path, "r", encoding="utf-8") as f:
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

    def get_bootstrap_key(self) -> str:
        """Get bootstrap key strictly from environment variable."""
        return os.getenv("VIENTO_BOOTSTRAP_KEY", "")


config_manager = ConfigManager()
