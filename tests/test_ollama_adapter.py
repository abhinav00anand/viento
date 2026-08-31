"""Mocked unit tests for Ollama backend adapter."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from viento.backends.ollama import OllamaAdapter


@pytest.fixture
def adapter():
    return OllamaAdapter(base_url="http://localhost:11434")


def test_ollama_adapter_name_and_capabilities(adapter):
    assert adapter.name() == "ollama"
    caps = adapter.capabilities()
    assert "chat" in caps
    assert "streaming" in caps


def test_health_success(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200

    with patch.object(adapter._client, "get", return_value=mock_resp):
        health = adapter.health()
        assert health is True


def test_health_offline(adapter):
    with patch.object(adapter._client, "get", side_effect=httpx.ConnectError("Offline")):
        health = adapter.health()
        assert health is False


def test_list_models_success(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3:latest", "details": {"quantization_level": "Q4_0"}}]
    }

    with patch.object(adapter._client, "get", return_value=mock_resp):
        models = adapter.list_models()
        assert len(models) == 1
        assert models[0]["id"] == "llama3:latest"


def test_generate_streaming_token_callbacks(adapter):
    lines = [
        '{"message": {"content": "Hello"}, "done": false}',
        '{"message": {"content": " world!"}, "done": true, "prompt_eval_count": 5, "eval_count": 2, "done_reason": "stop"}',
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = lines

    received = []
    def cb(chunk):
        received.append(chunk.delta)

    with patch.object(adapter._client, "build_request"), \
         patch.object(adapter._client, "send", return_value=mock_resp):
        result, handle = adapter.generate(
            job_id="job_ollama",
            model="llama3:latest",
            messages=[{"role": "user", "content": "Hi"}],
            callback=cb,
        )
        assert received == ["Hello", " world!"]
        assert result.total_tokens == 7
        assert result.finish_reason == "stop"


def test_embeddings_success(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.read.return_value = json.dumps({"embedding": [0.1, 0.2, 0.3], "prompt_eval_count": 3}).encode("utf-8")

    with patch.object(adapter._client, "build_request"), \
         patch.object(adapter._client, "send", return_value=mock_resp):
        res = adapter.embeddings("llama3:latest", ["Embedding text"])
        assert res.embeddings == [[0.1, 0.2, 0.3]]
        assert res.prompt_tokens == 3


def test_cancellation(adapter):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.close = MagicMock()

    adapter.cancel("job_nonexistent")
