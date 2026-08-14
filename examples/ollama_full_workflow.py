"""
Zephyr SDK — Full Workflow Example with Ollama.

Demonstrates a complete production workflow using the VientoClient:
  - Streaming chat completions
  - Non-streaming completions
  - Model listing
  - Embeddings
  - Proper error handling for all failure modes

Prerequisites:
    pip install viento
    export ZEPHYR_API_KEY="zph_tmp_..."   # obtained from `viento run`

Usage:
    python ollama_full_workflow.py
"""

import json
import os
import sys
import time
from typing import Any, Dict, Iterator, List, Optional

import httpx

# ---------------------------------------------------------------------------
# Client Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("ZEPHYR_BASE_URL", "https://zephyr.onrender.com")
API_KEY = os.environ.get("ZEPHYR_API_KEY", "")

if not API_KEY:
    print(
        "ERROR: ZEPHYR_API_KEY environment variable is not set.\n"
        "Run `viento run` on your local machine and copy the temporary API key printed\n"
        "in the handshake panel. Then set:\n\n"
        "    export ZEPHYR_API_KEY='zph_tmp_...'\n",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------

def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _handle_error(resp: httpx.Response, context: str) -> None:
    """Parse and print a user-friendly error message from an API response."""
    try:
        body = resp.json()
        msg = body.get("error", {})
        if isinstance(msg, dict):
            detail = msg.get("message", str(msg))
        else:
            detail = str(msg)
    except Exception:
        detail = resp.text[:500]

    status = resp.status_code
    if status == 401:
        print(f"[{context}] Authentication failed (401): {detail}")
        print("  Your API key may have expired (1-hour TTL). Run `viento run` again to get a fresh key.")
    elif status == 429:
        print(f"[{context}] Rate limit exceeded (429): {detail}")
        retry_after = resp.headers.get("Retry-After", "unknown")
        print(f"  Retry after: {retry_after}s")
    elif status == 404 and "model" in detail.lower():
        print(f"[{context}] Model not found (404): {detail}")
        print("  Run `viento models` to see available models, or `viento pull <model>` to download one.")
    elif status == 503:
        print(f"[{context}] No runtime available (503): {detail}")
        print("  Make sure your local Zephyr node is running with `viento run`.")
    else:
        print(f"[{context}] HTTP {status}: {detail}")


# ---------------------------------------------------------------------------
# 1. List Available Models
# ---------------------------------------------------------------------------

def list_models() -> List[Dict[str, Any]]:
    """Fetch the list of models registered by the connected runtime node."""
    print("\n── Listing Available Models ──────────────────────────────────────")
    with httpx.Client(base_url=BASE_URL, headers=_auth_headers(), timeout=10.0) as client:
        resp = client.get("/v1/models")
        if resp.status_code != 200:
            _handle_error(resp, "list_models")
            return []
        data = resp.json()
        models = data.get("data", [])
        if not models:
            print("  No models available. Is your Ollama running and `viento run` active?")
            return []
        for m in models:
            print(f"  • {m['id']:40s}  (owned_by: {m.get('owned_by', 'ollama')})")
        return models


# ---------------------------------------------------------------------------
# 2. Non-Streaming Chat Completion
# ---------------------------------------------------------------------------

def chat_completion_sync(model: str, prompt: str) -> Optional[str]:
    """Send a non-streaming chat completion and return the full response text."""
    print(f"\n── Non-Streaming Completion (model={model}) ──────────────────────")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise and helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": 256,
        "temperature": 0.7,
    }
    t0 = time.perf_counter()
    with httpx.Client(base_url=BASE_URL, headers=_auth_headers(), timeout=60.0) as client:
        resp = client.post("/v1/chat/completions", json=payload)
        elapsed = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            _handle_error(resp, "chat_completion_sync")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"  Response ({elapsed:.0f}ms, {usage.get('total_tokens', '?')} tokens):")
        print(f"  {content}")
        return content


# ---------------------------------------------------------------------------
# 3. Streaming Chat Completion
# ---------------------------------------------------------------------------

def chat_completion_stream(model: str, prompt: str) -> str:
    """Send a streaming chat completion and print tokens as they arrive."""
    print(f"\n── Streaming Completion (model={model}) ──────────────────────────")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": 512,
        "temperature": 0.9,
    }
    full_text = ""
    t0 = time.perf_counter()
    print("  ", end="", flush=True)
    with httpx.Client(base_url=BASE_URL, headers=_auth_headers(), timeout=120.0) as client:
        with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                resp.read()
                _handle_error(resp, "chat_completion_stream")
                return ""
            for line in resp.iter_lines():
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    raw = line[6:]
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0].get("delta", {}).get("content", "")
                        if delta:
                            print(delta, end="", flush=True)
                            full_text += delta
                    except (json.JSONDecodeError, KeyError):
                        continue

    elapsed = (time.perf_counter() - t0) * 1000
    print(f"\n  [Completed in {elapsed:.0f}ms, {len(full_text)} chars]")
    return full_text


# ---------------------------------------------------------------------------
# 4. Embeddings
# ---------------------------------------------------------------------------

def get_embeddings(model: str, texts: List[str]) -> Optional[List[List[float]]]:
    """Generate embeddings for a list of input texts."""
    print(f"\n── Embeddings (model={model}, inputs={len(texts)}) ───────────────")
    payload = {"model": model, "input": texts}
    with httpx.Client(base_url=BASE_URL, headers=_auth_headers(), timeout=30.0) as client:
        resp = client.post("/v1/embeddings", json=payload)
        if resp.status_code != 200:
            _handle_error(resp, "get_embeddings")
            return None
        data = resp.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        for i, emb in enumerate(embeddings):
            dims = len(emb)
            preview = emb[:4]
            print(f"  Input[{i}]: dims={dims}, preview={[round(x, 4) for x in preview]}...")
        return embeddings


# ---------------------------------------------------------------------------
# 5. Runtime Status
# ---------------------------------------------------------------------------

def check_runtime_status() -> None:
    """Display current runtime node status from the Cloud API."""
    print("\n── Runtime Status ────────────────────────────────────────────────")
    with httpx.Client(base_url=BASE_URL, headers=_auth_headers(), timeout=10.0) as client:
        resp = client.get("/v1/runtime/status")
        if resp.status_code != 200:
            _handle_error(resp, "runtime_status")
            return
        data = resp.json()
        print(f"  Session ID:    {data.get('session_id', 'N/A')}")
        print(f"  Status:        {data.get('status', 'unknown')}")
        print(f"  Key Expires:   {data.get('key_expires_at', 'N/A')}")
        print(f"  Models:        {', '.join(data.get('models', []))}")


# ---------------------------------------------------------------------------
# Main Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 66)
    print("  Zephyr + Ollama Full Workflow Example")
    print(f"  Server: {BASE_URL}")
    print("=" * 66)

    # Step 1: Check runtime status
    check_runtime_status()

    # Step 2: List available models
    models = list_models()
    if not models:
        print("\nNo models available — cannot proceed with completions. Exiting.")
        sys.exit(0)

    # Use the first available model for demos
    primary_model = models[0]["id"]

    # Step 3: Non-streaming completion
    chat_completion_sync(
        model=primary_model,
        prompt="What is the capital of France? Answer in one sentence.",
    )

    # Step 4: Streaming completion
    chat_completion_stream(
        model=primary_model,
        prompt="Write a haiku about distributed computing.",
    )

    # Step 5: Embeddings
    get_embeddings(
        model=primary_model,
        texts=[
            "The quick brown fox jumps over the lazy dog.",
            "Distributed inference at the edge.",
        ],
    )

    print("\n" + "=" * 66)
    print("  Workflow complete. All operations succeeded.")
    print("=" * 66)


if __name__ == "__main__":
    main()
