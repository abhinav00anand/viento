"""Production llama.cpp REST backend adapter for local llama.cpp server instances."""

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import httpx

from viento.backends.base import (
    BackendError,
    BackendOfflineError,
    BackendTimeoutError,
    ContextOverflowError,
    EmbeddingResult,
    ExecutionHandle,
    GenerationChunk,
    GenerationResult,
    InferenceBackend,
    ModelNotFoundError,
)

logger = logging.getLogger(__name__)


class LlamaCppExecutionHandle(ExecutionHandle):
    def __init__(self, job_id: str, response: httpx.Response):
        self.job_id = job_id
        self.response = response
        self._is_done = False
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            if not self._is_done and not self._cancelled:
                self._cancelled = True
                try:
                    self.response.close()
                    logger.info("Closed HTTP response stream for cancelled job %s", self.job_id)
                except Exception:
                    pass

    def is_done(self) -> bool:
        with self._lock:
            return self._is_done

    def mark_done(self):
        with self._lock:
            self._is_done = True


class LlamaCppAdapter(InferenceBackend):
    """Adapter connecting to llama.cpp server (default endpoint: http://localhost:8080)."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def name(self) -> str:
        return "llamacpp"

    def capabilities(self) -> List[str]:
        return ["chat", "embeddings", "streaming"]

    def health(self) -> bool:
        try:
            resp = self._client.get("/health")
            if resp.status_code == 200:
                return True
            resp_root = self._client.get("/")
            return resp_root.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            resp = self._client.get("/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", [])

            resp_props = self._client.get("/props")
            if resp_props.status_code == 200:
                props = resp_props.json()
                default_name = props.get("default_generation_settings", {}).get("model", "llama.cpp-model")
                return [{"id": default_name, "object": "model", "owned_by": "llama.cpp"}]

            return [{"id": "llama.cpp-default", "object": "model"}]
        except Exception as e:
            logger.error("Failed to list llama.cpp models: %s", e)
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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = stop

        req = self._client.build_request("POST", "/v1/chat/completions", json=payload)
        res = self._client.send(req, stream=True)

        if res.status_code != 200:
            res.close()
            raise RuntimeError(f"llama.cpp returned HTTP {res.status_code}: {res.text}")

        handle = LlamaCppExecutionHandle(job_id, res)
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
        is_estimated = False

        try:
            for line in res.iter_lines():
                if handle._cancelled:
                    finish_reason = "cancelled"
                    break
                line_str = line.strip()
                if not line_str or not line_str.startswith("data:"):
                    continue
                data_str = line_str[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue

                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {}).get("content", "")
                    if delta:
                        full_text += delta
                        if callback:
                            callback(GenerationChunk(delta=delta, index=chunk_idx))
                        chunk_idx += 1

                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0].get("finish_reason")

                usage = chunk.get("usage")
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)

        finally:
            handle.mark_done()
            res.close()

        if prompt_tokens == 0 and completion_tokens == 0:
            completion_tokens = chunk_idx
            total_tokens = completion_tokens
            is_estimated = True

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
        req = self._client.build_request(
            "POST",
            "/v1/embeddings",
            json={"model": model, "input": inputs},
        )
        res = self._client.send(req, stream=True)
        if res.status_code != 200:
            res.close()
            raise RuntimeError(f"llama.cpp embeddings failed HTTP {res.status_code}")

        handle = LlamaCppExecutionHandle(job_id or "embedding", res)
        if handle_callback:
            try:
                handle_callback(handle)
            except Exception:
                pass

        try:
            body_bytes = res.read()
            if handle._cancelled:
                return EmbeddingResult(embeddings=[], prompt_tokens=0, total_tokens=0, is_estimated=False)
            data = json.loads(body_bytes)
            items = data.get("data", [])
            embeddings_list = [item.get("embedding", []) for item in items]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens)

            is_estimated = (prompt_tokens == 0)
            if is_estimated:
                prompt_tokens = sum(len(t) // 4 for t in inputs)
                total_tokens = prompt_tokens

            return EmbeddingResult(
                embeddings=embeddings_list,
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                is_estimated=is_estimated,
            )
        finally:
            handle.mark_done()
            res.close()

    def cancel(self, job_id: str) -> None:
        pass
