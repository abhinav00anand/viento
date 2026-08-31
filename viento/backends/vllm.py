"""
Production Adapter for vLLM REST Server (http://localhost:8000/v1).
Supports OpenAI-compatible vLLM endpoints with ExecutionHandle TCP socket cancellation.
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

logger = logging.getLogger("viento.backends.vllm")


class VLLMExecutionHandle(ExecutionHandle):
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


class VLLMAdapter(InferenceBackend):
    def __init__(self, base_url: str = "http://localhost:8000/v1", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def name(self) -> str:
        return "vllm"

    def capabilities(self) -> List[str]:
        return ["chat", "embeddings", "streaming"]

    def health(self) -> bool:
        try:
            res = self._client.get("/models")
            return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            res = self._client.get("/models")
            if res.status_code != 200:
                return []
            data = res.json()
            models = []
            for item in data.get("data", []):
                models.append({
                    "id": item.get("id"),
                    "name": item.get("id"),
                    "status": "ready",
                    "backend": "vllm",
                    "context_length": 32768,
                    "quantization": "FP16",
                    "capabilities": ["chat", "streaming", "embeddings"],
                    "max_concurrency": 8,
                    "active_jobs": 0,
                })
            return models
        except Exception:
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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if stop:
            payload["stop"] = stop

        req = self._client.build_request("POST", "/chat/completions", json=payload)
        res = self._client.send(req, stream=True)

        if res.status_code != 200:
            res.close()
            raise RuntimeError(f"vLLM returned HTTP {res.status_code}: {res.text}")

        handle = VLLMExecutionHandle(job_id, res)
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
                if not line_str or not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                choice = data.get("choices", [{}])[0]
                delta = choice.get("delta", {}).get("content", "")
                if delta:
                    full_text += delta
                    if callback:
                        callback(GenerationChunk(delta=delta, index=chunk_idx))
                    chunk_idx += 1

                if choice.get("finish_reason"):
                    finish_reason = choice.get("finish_reason")

                usage = data.get("usage")
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", 0)

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
        req = self._client.build_request("POST", "/embeddings", json={"model": model, "input": inputs})
        res = self._client.send(req, stream=True)
        if res.status_code != 200:
            res.close()
            raise RuntimeError(f"vLLM embeddings failed HTTP {res.status_code}")

        handle = VLLMExecutionHandle(job_id or "embedding", res)
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
            embeddings = [item["embedding"] for item in data.get("data", [])]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            is_estimated = (prompt_tokens == 0)
            if is_estimated:
                prompt_tokens = sum(len(txt) // 4 for txt in inputs)
                total_tokens = prompt_tokens

            return EmbeddingResult(
                embeddings=embeddings,
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                is_estimated=is_estimated,
            )
        finally:
            handle.mark_done()
            res.close()

    def cancel(self, job_id: str) -> None:
        pass
