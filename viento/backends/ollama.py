"""
Production Adapter for Ollama REST Backend (http://localhost:11434).

Supports NDJSON streaming token extraction, ExecutionHandle TCP socket abort cancellation,
and accurate token count reporting.
"""

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from viento.backends.base import (
    EmbeddingResult,
    ExecutionHandle,
    GenerationChunk,
    GenerationResult,
    InferenceBackend,
)

logger = logging.getLogger("viento.backends.ollama")


class OllamaExecutionHandle(ExecutionHandle):
    """Execution handle wrapping an active Ollama HTTP streaming response."""

    def __init__(self, job_id: str, response: httpx.Response):
        self.job_id = job_id
        self.response = response
        self._is_done = False
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Close response stream instantly, aborting underlying TCP socket."""
        with self._lock:
            if not self._is_done and not self._cancelled:
                self._cancelled = True
                try:
                    self.response.close()
                    logger.info("Closed HTTP response stream for cancelled job %s", self.job_id)
                except Exception as exc:
                    logger.warning("Error closing response stream for job %s: %s", self.job_id, exc)

    def is_done(self) -> bool:
        with self._lock:
            return self._is_done

    def mark_done(self):
        with self._lock:
            self._is_done = True


class OllamaAdapter(InferenceBackend):
    """Ollama backend adapter interfacing with local Ollama service."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def name(self) -> str:
        return "ollama"

    def capabilities(self) -> List[str]:
        return ["chat", "embeddings", "streaming", "model_pull"]

    def health(self) -> bool:
        try:
            res = self._client.get("/")
            return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            res = self._client.get("/api/tags")
            if res.status_code != 200:
                return []
            data = res.json()
            models = []
            for item in data.get("models", []):
                models.append({
                    "id": item.get("name"),
                    "name": item.get("name"),
                    "status": "ready",
                    "backend": "ollama",
                    "context_length": 8192,
                    "quantization": item.get("details", {}).get("quantization_level", "unknown"),
                    "capabilities": ["chat", "streaming", "embeddings"],
                    "max_concurrency": 2,
                    "active_jobs": 0,
                })
            return models
        except Exception as exc:
            logger.error("Failed to list Ollama models: %s", exc)
            return []

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
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if stop:
            payload["options"]["stop"] = stop

        req = self._client.build_request("POST", "/api/chat", json=payload)
        res = self._client.send(req, stream=True)

        if res.status_code != 200:
            res.close()
            raise RuntimeError(f"Ollama returned HTTP {res.status_code}: {res.text}")

        handle = OllamaExecutionHandle(job_id, res)
        if handle_callback:
            try:
                handle_callback(handle)
            except Exception:
                pass

        full_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        finish_reason = "stop"
        chunk_idx = 0

        try:
            for line in res.iter_lines():
                if handle._cancelled:
                    finish_reason = "cancelled"
                    break
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                except Exception:
                    continue

                delta = data.get("message", {}).get("content", "")
                if delta:
                    full_text += delta
                    if callback:
                        callback(GenerationChunk(delta=delta, index=chunk_idx))
                    chunk_idx += 1

                if data.get("done"):
                    prompt_tokens = data.get("prompt_eval_count", 0)
                    completion_tokens = data.get("eval_count", 0)
                    total_tokens = prompt_tokens + completion_tokens
                    finish_reason = data.get("done_reason", "stop")
                    break

        finally:
            handle.mark_done()
            res.close()

        is_estimated = (prompt_tokens == 0 and completion_tokens == 0)
        if is_estimated:
            completion_tokens = chunk_idx
            total_tokens = completion_tokens

        result = GenerationResult(
            full_text=full_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
            is_estimated=is_estimated,
        )
        return result, handle

    def embeddings(
        self,
        model: str,
        inputs: List[str],
        job_id: Optional[str] = None,
        handle_callback: Optional[Callable[[ExecutionHandle], None]] = None,
    ) -> EmbeddingResult:
        all_embeddings: List[List[float]] = []
        total_prompt_tokens = 0
        is_estimated = False

        for input_text in inputs:
            payload = {"model": model, "prompt": input_text}
            req = self._client.build_request("POST", "/api/embeddings", json=payload)
            res = self._client.send(req, stream=True)

            if res.status_code != 200:
                res.close()
                req = self._client.build_request("POST", "/api/embed", json={"model": model, "input": input_text})
                res = self._client.send(req, stream=True)
                if res.status_code != 200:
                    res.close()
                    raise RuntimeError(f"Ollama embedding failed HTTP {res.status_code}")

            handle = OllamaExecutionHandle(job_id or "embedding", res)
            if handle_callback:
                try:
                    handle_callback(handle)
                except Exception:
                    pass

            try:
                body_bytes = res.read()
                if handle._cancelled:
                    break
                data = json.loads(body_bytes)
                emb = data.get("embedding") or (data.get("embeddings", [[]])[0])
                all_embeddings.append(emb)

                tokens = data.get("prompt_eval_count", 0)
                if tokens == 0:
                    tokens = max(1, len(input_text) // 4)
                    is_estimated = True
                total_prompt_tokens += tokens
            finally:
                handle.mark_done()
                res.close()

            if handle._cancelled:
                break

        return EmbeddingResult(
            embeddings=all_embeddings,
            prompt_tokens=total_prompt_tokens,
            total_tokens=total_prompt_tokens,
            is_estimated=is_estimated,
        )

    def cancel(self, job_id: str) -> None:
        pass
