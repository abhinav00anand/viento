"""
High-Level Python Client for Viento Cloud AI API.

Provides an OpenAI-compatible Python interface for invoking LLM chat completions
and vector embeddings across the Viento distributed mesh network.
"""

import os
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any, Dict, List, Optional, Union

import httpx


class ChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class ChatChoice:
    def __init__(self, index: int, message: ChatMessage, finish_reason: str = "stop"):
        self.index = index
        self.message = message
        self.finish_reason = finish_reason


class ChatCompletionResponse:
    def __init__(
        self,
        id: str,
        created: int,
        model: str,
        choices: List[ChatChoice],
        usage: Optional[Dict[str, int]] = None,
    ):
        self.id = id
        self.created = created
        self.model = model
        self.choices = choices
        self.usage = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


class ChatChunkDelta:
    def __init__(self, content: str, role: str = "assistant"):
        self.content = content
        self.role = role


class ChatChunkChoice:
    def __init__(self, index: int, delta: ChatChunkDelta, finish_reason: Optional[str] = None):
        self.index = index
        self.delta = delta
        self.finish_reason = finish_reason


class ChatCompletionChunk:
    def __init__(self, id: str, created: int, model: str, choices: List[ChatChunkChoice]):
        self.id = id
        self.created = created
        self.model = model
        self.choices = choices


class ChatCompletions:
    """OpenAI-style completions interface."""

    def __init__(self, client: "VientoClient"):
        self._client = client

    def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 512,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ChatCompletionResponse, Generator[ChatCompletionChunk, None, None]]:
        return self._client.chat_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            **kwargs,
        )


class AsyncChatCompletions:
    """Async OpenAI-style completions interface."""

    def __init__(self, client: "AsyncVientoClient"):
        self._client = client

    async def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 512,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ChatCompletionResponse, AsyncGenerator[ChatCompletionChunk, None]]:
        return await self._client.chat_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            **kwargs,
        )


class Chat:
    def __init__(self, client: "VientoClient"):
        self.completions = ChatCompletions(client)


class AsyncChat:
    def __init__(self, client: "AsyncVientoClient"):
        self.completions = AsyncChatCompletions(client)


class EmbeddingObject:
    def __init__(self, index: int, embedding: List[float]):
        self.index = index
        self.embedding = embedding


class EmbeddingResponse:
    def __init__(
        self,
        data: List[EmbeddingObject],
        model: str,
        usage: Optional[Dict[str, int]] = None,
    ):
        self.data = data
        self.model = model
        self.usage = usage or {"prompt_tokens": 0, "total_tokens": 0}


class Embeddings:
    """OpenAI-style embeddings interface."""

    def __init__(self, client: "VientoClient"):
        self._client = client

    def create(
        self,
        model: str,
        input: Union[str, List[str]],
        **kwargs: Any,
    ) -> EmbeddingResponse:
        return self._client.create_embedding(model=model, input=input, **kwargs)


class AsyncEmbeddings:
    """Async OpenAI-style embeddings interface."""

    def __init__(self, client: "AsyncVientoClient"):
        self._client = client

    async def create(
        self,
        model: str,
        input: Union[str, List[str]],
        **kwargs: Any,
    ) -> EmbeddingResponse:
        return await self._client.create_embedding(model=model, input=input, **kwargs)


class VientoClient:
    """
    Synchronous Python Client for calling Viento Cloud APIs.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.base_url = (
            base_url or os.getenv("VIENTO_BASE_URL", "https://viento.onrender.com")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("VIENTO_API_KEY", "")
        self.timeout = timeout

        self.chat = Chat(self)
        self.embeddings = Embeddings(self)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 512,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ChatCompletionResponse, Generator[ChatCompletionChunk, None, None]]:
        """Submit a chat completion request to the Viento Cloud gateway."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **kwargs,
        }

        if stream:
            return self._stream_chat_completion(url, payload)

        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(url, json=payload, headers=self._headers())
            if res.status_code != 200:
                raise RuntimeError(f"Viento API Error ({res.status_code}): {res.text}")

            data = res.json()
            choices = [
                ChatChoice(
                    index=c.get("index", 0),
                    message=ChatMessage(
                        role=c.get("message", {}).get("role", "assistant"),
                        content=c.get("message", {}).get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
                for c in data.get("choices", [])
            ]

            return ChatCompletionResponse(
                id=data.get("id", f"chatcmpl-{int(time.time())}"),
                created=data.get("created", int(time.time())),
                model=data.get("model", model),
                choices=choices,
                usage=data.get("usage"),
            )

    def create_embedding(
        self, model: str, input: Union[str, List[str]], **kwargs: Any
    ) -> EmbeddingResponse:
        """Submit an embedding creation request to the Viento Cloud gateway."""
        url = f"{self.base_url}/v1/embeddings"
        payload = {"model": model, "input": input, **kwargs}
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(url, json=payload, headers=self._headers())
            if res.status_code != 200:
                raise RuntimeError(f"Viento Embedding API Error ({res.status_code}): {res.text}")

            data = res.json()
            objects = [
                EmbeddingObject(index=item.get("index", idx), embedding=item.get("embedding", []))
                for idx, item in enumerate(data.get("data", []))
            ]
            return EmbeddingResponse(
                data=objects,
                model=data.get("model", model),
                usage=data.get("usage"),
            )

    def _stream_chat_completion(
        self, url: str, payload: Dict[str, Any]
    ) -> Generator[ChatCompletionChunk, None, None]:
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, json=payload, headers=self._headers()) as res:
                if res.status_code != 200:
                    raise RuntimeError(f"Viento Streaming API Error ({res.status_code})")
                for line in res.iter_lines():
                    if line.startswith("data: "):
                        content_str = line[6:].strip()
                        if content_str == "[DONE]":
                            break
                        try:
                            import json

                            data = json.loads(content_str)
                            chunk_choices = [
                                ChatChunkChoice(
                                    index=c.get("index", 0),
                                    delta=ChatChunkDelta(
                                        content=c.get("delta", {}).get("content", ""),
                                        role=c.get("delta", {}).get("role", "assistant"),
                                    ),
                                    finish_reason=c.get("finish_reason"),
                                )
                                for c in data.get("choices", [])
                            ]
                            yield ChatCompletionChunk(
                                id=data.get("id", f"chatcmpl-{int(time.time())}"),
                                created=data.get("created", int(time.time())),
                                model=data.get("model", payload.get("model")),
                                choices=chunk_choices,
                            )
                        except Exception:
                            continue

    def list_models(self) -> List[Dict[str, Any]]:
        """List active available models across the Viento mesh."""
        url = f"{self.base_url}/v1/models"
        with httpx.Client(timeout=10.0) as client:
            res = client.get(url, headers=self._headers())
            if res.status_code == 200:
                return res.json().get("data", [])
            raise RuntimeError(f"Failed to list models ({res.status_code}): {res.text}")

    def health_check(self) -> Dict[str, Any]:
        """Perform health check against Viento Cloud endpoint."""
        url = f"{self.base_url}/healthz"
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url)
            return {
                "status_code": res.status_code,
                "data": res.json() if res.status_code == 200 else res.text,
            }


class AsyncVientoClient:
    """
    Asynchronous Python Client for calling Viento Cloud APIs.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.base_url = (
            base_url or os.getenv("VIENTO_BASE_URL", "https://viento.onrender.com")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("VIENTO_API_KEY", "")
        self.timeout = timeout

        self.chat = AsyncChat(self)
        self.embeddings = AsyncEmbeddings(self)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 512,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ChatCompletionResponse, AsyncGenerator[ChatCompletionChunk, None]]:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **kwargs,
        }

        if stream:
            return self._stream_chat_completion(url, payload)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, json=payload, headers=self._headers())
            if res.status_code != 200:
                raise RuntimeError(f"Viento API Error ({res.status_code}): {res.text}")

            data = res.json()
            choices = [
                ChatChoice(
                    index=c.get("index", 0),
                    message=ChatMessage(
                        role=c.get("message", {}).get("role", "assistant"),
                        content=c.get("message", {}).get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
                for c in data.get("choices", [])
            ]

            return ChatCompletionResponse(
                id=data.get("id", f"chatcmpl-{int(time.time())}"),
                created=data.get("created", int(time.time())),
                model=data.get("model", model),
                choices=choices,
                usage=data.get("usage"),
            )

    async def create_embedding(
        self, model: str, input: Union[str, List[str]], **kwargs: Any
    ) -> EmbeddingResponse:
        """Submit an embedding creation request asynchronously to the Viento Cloud gateway."""
        url = f"{self.base_url}/v1/embeddings"
        payload = {"model": model, "input": input, **kwargs}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, json=payload, headers=self._headers())
            if res.status_code != 200:
                raise RuntimeError(f"Viento Embedding API Error ({res.status_code}): {res.text}")

            data = res.json()
            objects = [
                EmbeddingObject(index=item.get("index", idx), embedding=item.get("embedding", []))
                for idx, item in enumerate(data.get("data", []))
            ]
            return EmbeddingResponse(
                data=objects,
                model=data.get("model", model),
                usage=data.get("usage"),
            )

    async def _stream_chat_completion(
        self, url: str, payload: Dict[str, Any]
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as res:
                if res.status_code != 200:
                    raise RuntimeError(f"Viento Streaming API Error ({res.status_code})")
                async for line in res.aiter_lines():
                    if line.startswith("data: "):
                        content_str = line[6:].strip()
                        if content_str == "[DONE]":
                            break
                        try:
                            import json

                            data = json.loads(content_str)
                            chunk_choices = [
                                ChatChunkChoice(
                                    index=c.get("index", 0),
                                    delta=ChatChunkDelta(
                                        content=c.get("delta", {}).get("content", ""),
                                        role=c.get("delta", {}).get("role", "assistant"),
                                    ),
                                    finish_reason=c.get("finish_reason"),
                                )
                                for c in data.get("choices", [])
                            ]
                            yield ChatCompletionChunk(
                                id=data.get("id", f"chatcmpl-{int(time.time())}"),
                                created=data.get("created", int(time.time())),
                                model=data.get("model", payload.get("model")),
                                choices=chunk_choices,
                            )
                        except Exception:
                            continue

    async def list_models(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v1/models"
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=self._headers())
            if res.status_code == 200:
                return res.json().get("data", [])
            raise RuntimeError(f"Failed to list models ({res.status_code}): {res.text}")

    async def health_check(self) -> Dict[str, Any]:
        url = f"{self.base_url}/healthz"
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url)
            return {
                "status_code": res.status_code,
                "data": res.json() if res.status_code == 200 else res.text,
            }
