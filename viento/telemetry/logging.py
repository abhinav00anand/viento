"""Structured JSON and console logger with automatic secret masking."""

import json
import logging
import re
import sys
import time
from typing import Any, Dict


class SecretMasker:
    """Regex-based secret masker for sensitive API keys, tokens, and credentials."""

    PATTERNS = [
        # Viento temporary and live keys
        (re.compile(r"vnt_tmp_[A-Za-z0-9_\-]+"), lambda m: "vnt_tmp_****"),
        (re.compile(r"zph_live_[A-Za-z0-9_\-]+"), lambda m: "zph_live_****"),
        # OpenAI style API keys
        (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), lambda m: "sk-****"),
        # Authorization bearer tokens
        (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1[REDACTED]"),
        # Password / secret key-value pairs
        (
            re.compile(
                r"(password|token|secret|api_key|auth_token)\s*=\s*['\"]?[^'\"\s,]+['\"]?",
                re.IGNORECASE,
            ),
            r"\1=[REDACTED]",
        ),
    ]

    @classmethod
    def mask(cls, text: str) -> str:
        """Applies all secret masking regex patterns to input text."""
        if not text or not isinstance(text, str):
            return text

        masked_text = text
        for pattern, replacement in cls.PATTERNS:
            if callable(replacement):
                masked_text = pattern.sub(replacement, masked_text)
            else:
                masked_text = pattern.sub(replacement, masked_text)
        return masked_text

    @classmethod
    def mask_object(cls, obj: Any) -> Any:
        """Recursively applies secret masking to strings inside dicts/lists/objects."""
        if isinstance(obj, str):
            return cls.mask(obj)
        elif isinstance(obj, dict):
            return {cls.mask(str(k)): cls.mask_object(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls.mask_object(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(cls.mask_object(item) for item in obj)
        return obj


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with secret masking."""

    def __init__(self, service_name: str = "viento"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        raw_msg = record.getMessage()
        masked_msg = SecretMasker.mask(raw_msg)

        log_payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "created": record.created,
            "level": record.levelname,
            "logger": record.name,
            "service": self.service_name,
            "message": masked_msg,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include trace_id or extra attributes if attached to record
        if hasattr(record, "trace_id"):
            log_payload["trace_id"] = SecretMasker.mask(str(record.trace_id))

        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_payload["extra"] = SecretMasker.mask_object(record.extra_data)

        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            log_payload["exception"] = SecretMasker.mask(exc_text)

        return json.dumps(log_payload)


class ConsoleFormatter(logging.Formatter):
    """Console formatter with color coding and secret masking."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        raw_msg = record.getMessage()
        masked_msg = SecretMasker.mask(raw_msg)

        level_name = record.levelname
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))

        if self.use_colors and level_name in self.COLORS:
            color = self.COLORS[level_name]
            reset = self.COLORS["RESET"]
            prefix = f"{timestamp} [{color}{level_name:8s}{reset}] [{record.name}]:"
        else:
            prefix = f"{timestamp} [{level_name:8s}] [{record.name}]:"

        formatted = f"{prefix} {masked_msg}"

        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            formatted += f"\n{SecretMasker.mask(exc_text)}"

        return formatted


class VientoLogger:
    """Helper wrapper for configured loggers."""

    @staticmethod
    def get_logger(
        name: str = "viento",
        log_level: str = "INFO",
        json_output: bool = True,
        service_name: str = "viento",
    ) -> logging.Logger:
        """Configures and returns a logger instance with secret masking.

        Args:
            name: Logger name.
            log_level: Desired log level string (DEBUG, INFO, WARNING, ERROR).
            json_output: If True, uses JSON formatter; otherwise uses console formatter.
            service_name: Service name included in JSON output.

        Returns:
            logging.Logger instance.
        """
        logger = logging.getLogger(name)

        numeric_level = getattr(logging, log_level.upper(), logging.INFO)
        logger.setLevel(numeric_level)

        # Avoid duplicating handlers if already configured
        if logger.handlers:
            return logger

        logger.propagate = False

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric_level)

        if json_output:
            handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
        else:
            handler.setFormatter(ConsoleFormatter(use_colors=True))

        logger.addHandler(handler)
        return logger


def get_logger(
    name: str = "viento",
    log_level: str = "INFO",
    json_output: bool = True,
) -> logging.Logger:
    """Convenience alias function to get a VientoLogger."""
    return VientoLogger.get_logger(name=name, log_level=log_level, json_output=json_output)
