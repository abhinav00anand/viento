"""
Abstract Base Classes for Inference Backends and Execution Handles.

Defines the execution handle contract for non-destructive HTTP stream cancellation,
backend exceptions, and thread-safe compute resource release.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel


class BackendError(Exception):
    """Base exception for inference backend errors."""
    pass


class BackendOfflineError(BackendError):
    """Raised when the backend server is unreachable or offline."""
    pass


class BackendTimeoutError(BackendError):
    """Raised when request times out on backend."""
    pass


class ModelNotFoundError(BackendError):
    """Raised when a requested model is not found on the backend."""
    pass


class ContextLengthExceededError(BackendError):
    """Raised when request prompt tokens exceed backend context length limits."""
    pass


ContextOverflowError = ContextLengthExceededError


class ExecutionHandle(ABC):
    """Abstract execution handle wrapping an active inference HTTP response stream."""

    @abstractmethod
    def cancel(self) -> None:
        """Cancel execution and close underlying HTTP socket connection immediately."""
        pass

    @abstractmethod
    def is_done(self) -> bool:
        """Check if execution has completed or aborted."""
        pass


class GenerationChunk(BaseModel):
    delta: str
    finish_reason: Optional[str] = None
    index: int = 0


class GenerationResult(BaseModel):
    full_text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    is_estimated: bool = False


class EmbeddingResult(BaseModel):
    embeddings: List[List[float]]
    prompt_tokens: int = 0
    total_tokens: int = 0
    is_estimated: bool = False


class InferenceBackend(ABC):
    """Abstract base class for all local inference engine adapters (Ollama, vLLM, llama.cpp)."""

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def capabilities(self) -> List[str]:
        pass

    @abstractmethod
    def health(self) -> bool:
        pass

    @abstractmethod
    def list_models(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def generate(
        self,
        job_id: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 512,
        callback: Optional[Callable[[GenerationChunk], None]] = None,
        stop: Optional[List[str]] = None,
        handle_callback: Optional[Callable[[ExecutionHandle], None]] = None,
    ) -> Tuple[GenerationResult, ExecutionHandle]:
        pass

    @abstractmethod
    def embeddings(
        self,
        model: str,
        inputs: List[str],
        job_id: Optional[str] = None,
        handle_callback: Optional[Callable[[ExecutionHandle], None]] = None,
    ) -> EmbeddingResult:
        pass

    @abstractmethod
    def cancel(self, job_id: str) -> None:
        pass
