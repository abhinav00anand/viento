"""Inference backend adapters for local and cloud LLM runtime engines."""

from typing import Optional
from viento.backends.base import (
    InferenceBackend,
    BackendError,
    BackendOfflineError,
    ModelNotFoundError,
    ContextOverflowError,
    BackendTimeoutError,
)
from viento.backends.ollama import OllamaAdapter
from viento.backends.llamacpp import LlamaCppAdapter
from viento.backends.vllm import VLLMAdapter


def get_backend_adapter(backend_name: str = "ollama", base_url: Optional[str] = None) -> InferenceBackend:
    """
    Factory function to instantiate the matching backend adapter class
    based on backend_name string ("ollama", "vllm", "llamacpp").
    """
    name = (backend_name or "ollama").strip().lower()
    if name in ("vllm", "vllm_adapter"):
        url = base_url or "http://localhost:8000/v1"
        return VLLMAdapter(base_url=url)
    elif name in ("llamacpp", "llama_cpp", "llama.cpp"):
        url = base_url or "http://localhost:8080"
        return LlamaCppAdapter(base_url=url)
    else:
        url = base_url or "http://localhost:11434"
        return OllamaAdapter(base_url=url)


__all__ = [
    "InferenceBackend",
    "BackendError",
    "BackendOfflineError",
    "ModelNotFoundError",
    "ContextOverflowError",
    "BackendTimeoutError",
    "OllamaAdapter",
    "LlamaCppAdapter",
    "VLLMAdapter",
    "get_backend_adapter",
]
