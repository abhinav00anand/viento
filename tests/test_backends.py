"""Mocked unit tests for llama.cpp and vLLM backend adapters."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from viento.backends.llamacpp import LlamaCppAdapter
from viento.backends.vllm import VLLMAdapter

# --- llama.cpp Tests ---


@pytest.fixture
def llamacpp_adapter():
    return LlamaCppAdapter(base_url="http://localhost:8080")


def test_llamacpp_adapter_name_and_capabilities(llamacpp_adapter):
    assert llamacpp_adapter.name() == "llamacpp"
    caps = llamacpp_adapter.capabilities()
    assert "chat" in caps
    assert "streaming" in caps
    assert "embeddings" in caps


def test_llamacpp_health_success(llamacpp_adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200

    with patch.object(llamacpp_adapter._client, "get", return_value=mock_resp):
        health = llamacpp_adapter.health()
        assert health is True


def test_llamacpp_list_models_v1(llamacpp_adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "llama-2-7b.Q4_0.gguf"}]}

    with patch.object(llamacpp_adapter._client, "get", return_value=mock_resp):
        models = llamacpp_adapter.list_models()
        assert len(models) == 1
        assert models[0]["id"] == "llama-2-7b.Q4_0.gguf"


def test_llamacpp_generate_streaming(llamacpp_adapter):
    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}',
        'data: {"choices": [{"delta": {"content": " world!"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = sse_lines

    received = []

    def cb(chunk):
        received.append(chunk.delta)

    with (
        patch.object(llamacpp_adapter._client, "build_request"),
        patch.object(llamacpp_adapter._client, "send", return_value=mock_resp),
    ):
        result, handle = llamacpp_adapter.generate(
            job_id="job_1",
            model="llama2",
            messages=[{"role": "user", "content": "Test"}],
            callback=cb,
        )
        assert received == ["Hello", " world!"]
        assert result.finish_reason == "stop"


def test_llamacpp_embeddings(llamacpp_adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.read.return_value = json.dumps(
        {
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }
    ).encode("utf-8")

    with (
        patch.object(llamacpp_adapter._client, "build_request"),
        patch.object(llamacpp_adapter._client, "send", return_value=mock_resp),
    ):
        res = llamacpp_adapter.embeddings("llama2", ["Embedding text"])
        assert res.embeddings == [[0.1, 0.2, 0.3]]
        assert res.total_tokens == 5


# --- vLLM Tests ---


@pytest.fixture
def vllm_adapter():
    return VLLMAdapter(base_url="http://localhost:8000/v1")


def test_vllm_adapter_name_and_capabilities(vllm_adapter):
    assert vllm_adapter.name() == "vllm"
    caps = vllm_adapter.capabilities()
    assert "chat" in caps
    assert "streaming" in caps


def test_vllm_generate_streaming(vllm_adapter):
    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}',
        'data: {"choices": [{"delta": {"content": " world!"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = sse_lines

    received = []

    def cb(chunk):
        received.append(chunk.delta)

    with (
        patch.object(vllm_adapter._client, "build_request"),
        patch.object(vllm_adapter._client, "send", return_value=mock_resp),
    ):
        result, handle = vllm_adapter.generate(
            job_id="job_2",
            model="mistral-7b",
            messages=[{"role": "user", "content": "Test"}],
            callback=cb,
        )
        assert received == ["Hello", " world!"]
        assert result.finish_reason == "stop"
