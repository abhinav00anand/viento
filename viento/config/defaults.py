"""
Zephyr SDK Default Configuration & Environment Variable Handling.

Defines canonical defaults for all configurable parameters, maps environment
variables to configuration keys, and provides a validation utility for
detecting misconfigured environments before connection attempts.
"""

import logging
import os
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from viento.config.loader import ZephyrConfig

logger = logging.getLogger("zephyr.config.defaults")

# ---------------------------------------------------------------------------
# Canonical Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    # Cloud Gateway
    "server_url": "wss://viento.onrender.com/ws/runtime",
    "http_url": "https://viento.onrender.com",

    # Local Backend
    "ollama_url": "http://localhost:11434",

    # Node Identity
    "node_name": "zephyr-node",

    # Concurrency
    "max_concurrency": 1,

    # Heartbeat
    "heartbeat_interval": 15,       # seconds between heartbeat pings
    "heartbeat_deadline": 45,       # seconds before server marks node offline

    # Job Limits
    "job_timeout": 120,             # per-job deadline in seconds
    "max_queue_depth": 50,          # maximum jobs waiting per runtime

    # API Key
    "token_ttl": 3600,              # temporary key lifetime (1 hour)

    # Logging
    "log_level": "INFO",
    "log_json": False,              # if True, emit structured JSON logs

    # Reconnection
    "reconnect_base_delay": 1.0,    # seconds — first backoff interval
    "reconnect_max_delay": 30.0,    # seconds — upper cap on backoff
    "reconnect_jitter_factor": 0.2, # fraction of current backoff to randomise
}

# ---------------------------------------------------------------------------
# Environment Variable Mapping
# ---------------------------------------------------------------------------

# Maps OS environment variable name -> ZephyrConfig attribute name
ENV_VAR_MAPPING: Dict[str, str] = {
    "ZEPHYR_SERVER_URL":           "server_url",
    "ZEPHYR_HTTP_URL":             "http_url",
    "ZEPHYR_OLLAMA_URL":           "ollama_url",
    "ZEPHYR_NODE_NAME":            "node_name",
    "ZEPHYR_MAX_CONCURRENCY":      "max_concurrency",
    "ZEPHYR_HEARTBEAT_INTERVAL":   "heartbeat_interval",
    "ZEPHYR_HEARTBEAT_DEADLINE":   "heartbeat_deadline",
    "ZEPHYR_JOB_TIMEOUT":          "job_timeout",
    "ZEPHYR_MAX_QUEUE_DEPTH":      "max_queue_depth",
    "ZEPHYR_TOKEN_TTL":            "token_ttl",
    "ZEPHYR_LOG_LEVEL":            "log_level",
    "ZEPHYR_LOG_JSON":             "log_json",
    "ZEPHYR_RECONNECT_BASE_DELAY": "reconnect_base_delay",
    "ZEPHYR_RECONNECT_MAX_DELAY":  "reconnect_max_delay",
}

# Numeric fields that should be cast to int
_INT_FIELDS = {
    "max_concurrency", "heartbeat_interval", "heartbeat_deadline",
    "job_timeout", "max_queue_depth", "token_ttl",
}

# Numeric fields that should be cast to float
_FLOAT_FIELDS = {
    "reconnect_base_delay", "reconnect_max_delay", "reconnect_jitter_factor",
}

# Boolean fields
_BOOL_FIELDS = {"log_json"}


def apply_env_overrides(config: "ZephyrConfig") -> "ZephyrConfig":
    """Read environment variables and override matching ZephyrConfig attributes.

    Environment variables always take precedence over values stored in
    ``~/.viento/config.toml``. This enables container-friendly deployment
    where all configuration is injected at runtime via env vars.

    Args:
        config: A loaded :class:`ZephyrConfig` instance to mutate in-place.

    Returns:
        The same ``config`` object with any env-var overrides applied.

    Example::

        os.environ["ZEPHYR_SERVER_URL"] = "wss://myhost.example.com/ws/runtime"
        cfg = apply_env_overrides(config_manager.load_config())
        # cfg.server_url == "wss://myhost.example.com/ws/runtime"
    """
    applied: List[str] = []

    for env_key, attr_name in ENV_VAR_MAPPING.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue

        try:
            if attr_name in _INT_FIELDS:
                value: Any = int(raw)
            elif attr_name in _FLOAT_FIELDS:
                value = float(raw)
            elif attr_name in _BOOL_FIELDS:
                value = raw.strip().lower() in ("1", "true", "yes", "on")
            else:
                value = raw.strip()

            setattr(config, attr_name, value)
            applied.append(f"{env_key}={raw!r} -> {attr_name}={value!r}")

        except (ValueError, TypeError) as exc:
            logger.warning(
                "Could not apply env override %s=%r for attribute '%s': %s",
                env_key, raw, attr_name, exc,
            )

    if applied:
        logger.debug("Applied %d environment override(s): %s", len(applied), applied)

    return config


def validate_config(config: "ZephyrConfig") -> List[str]:
    """Validate a :class:`ZephyrConfig` instance and return a list of warnings.

    This is a non-blocking pre-flight check.  It returns warnings rather than
    raising exceptions so that the caller can decide how to surface them
    (e.g., printed by ``viento doctor`` or logged at startup).

    Args:
        config: The configuration to validate.

    Returns:
        A list of human-readable warning strings.  Empty list means no issues.

    Warnings are raised for:
    - ``server_url`` that does not start with ``wss://`` or ``ws://``
    - ``ollama_url`` that does not start with ``http://`` or ``https://``
    - ``max_concurrency`` <= 0
    - ``heartbeat_interval`` >= ``heartbeat_deadline`` (will always time out)
    - ``job_timeout`` <= 0
    - ``token_ttl`` outside the range [60, 86400] seconds
    - ``reconnect_max_delay`` < ``reconnect_base_delay``
    """
    warnings: List[str] = []

    # server_url
    if not config.server_url.startswith(("wss://", "ws://")):
        warnings.append(
            f"server_url '{config.server_url}' should start with 'wss://' (or 'ws://' for local dev). "
            "Using a non-WebSocket URL will cause connection failures."
        )

    # ollama_url
    if not config.ollama_url.startswith(("http://", "https://")):
        warnings.append(
            f"ollama_url '{config.ollama_url}' should start with 'http://' or 'https://'. "
            "This URL is used for Ollama REST API calls."
        )

    # max_concurrency
    if config.max_concurrency <= 0:
        warnings.append(
            f"max_concurrency={config.max_concurrency} is invalid. Must be >= 1. "
            "Defaulting to 1 will be applied at runtime."
        )

    # heartbeat timing
    if hasattr(config, "heartbeat_interval") and hasattr(config, "heartbeat_deadline"):
        if config.heartbeat_interval >= config.heartbeat_deadline:
            warnings.append(
                f"heartbeat_interval ({config.heartbeat_interval}s) >= heartbeat_deadline "
                f"({config.heartbeat_deadline}s). The server will always evict this node before "
                "the next heartbeat is sent. Increase heartbeat_deadline or decrease heartbeat_interval."
            )

    # job_timeout
    if hasattr(config, "job_timeout") and config.job_timeout <= 0:
        warnings.append(
            f"job_timeout={config.job_timeout} is invalid. Must be a positive number of seconds."
        )

    # token_ttl
    if hasattr(config, "token_ttl"):
        if not (60 <= config.token_ttl <= 86400):
            warnings.append(
                f"token_ttl={config.token_ttl}s is outside the recommended range [60, 86400]. "
                "Very short TTLs cause frequent re-authentication; very long TTLs increase security risk."
            )

    # reconnect delays
    if hasattr(config, "reconnect_base_delay") and hasattr(config, "reconnect_max_delay"):
        if config.reconnect_max_delay < config.reconnect_base_delay:
            warnings.append(
                f"reconnect_max_delay ({config.reconnect_max_delay}s) < reconnect_base_delay "
                f"({config.reconnect_base_delay}s). Max delay must be >= base delay."
            )

    return warnings
