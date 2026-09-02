#!/usr/bin/env python3
"""
Antigravity PR Review & Deep Check Agent for Viento SDK.

This script runs an autonomous code review powered by the Google Antigravity SDK
(or Google Gemini API) specifically customized for the Viento SDK (viento).
Performs full analysis with deep architectural checks, highlights what is wrong,
specifies what is needed with concrete code suggestions, and posts comments
directly to GitHub Pull Requests.
"""

import argparse
import asyncio
import os
import re
import subprocess
import sys
from typing import Optional, Dict, Any


VIENTO_REVIEW_INSTRUCTIONS = """
You are Antigravity, an expert software engineering and architectural review agent
specializing in the Viento Distributed Inference Mesh SDK (Python package: `viento`).

Your mission is to perform a rigorous code review and deep architectural check of the provided Git pull request.

## Viento SDK Core Invariants & Architectural Rules:
1. **Canonical Envelope Protocol (V1.0)**:
   - Every WebSocket frame must strictly serialize/deserialize to Pydantic V2 `ProtocolEnvelope`.
   - `extra="forbid"` must always be maintained.
   - Monotonic sequence numbers must be respected across sessions.
2. **Backend Adapter Lifecycles (`InferenceBackend`)**:
   - `generate(...)` and `embeddings(...)` must invoke `handle_callback` BEFORE any blocking I/O.
   - Every execution must return an `ExecutionHandle` allowing instant non-blocking cancellation.
   - Cancellation must close the underlying TCP/HTTP socket cleanly without leaving zombie inference worker threads.
3. **Backpressure & Flow Control**:
   - Token streaming queues must enforce backpressure with timeouts: `wait_for(put(), timeout=5.0)`.
   - Never silently discard or drop generated tokens under heavy load.
4. **Telemetry & Zero-Trust Security**:
   - Strictly use `SecretMasker` from `viento.telemetry.logging` for masking secrets. Never log raw API tokens.
   - Use standard logging via `logging.getLogger("viento.<module>")` — NEVER use raw `print()` statements in production code.
5. **Code Style & Quality**:
   - Follow PEP 8 and `black` formatting (100-character line limit) and `ruff` rules.
   - All public functions and classes must have complete type annotations and Google-style docstrings.
   - Tests must use `pytest` and `pytest-asyncio` with strict mock isolation where external backends (Ollama/vLLM) are called.

## Review Structure & Requirements:
You MUST format your analysis into these exact sections:

### 1. 📊 Executive Summary & Verdict
- State the purpose of the PR and overall implementation health.
- Verdict: **APPROVE**, **REQUEST_CHANGES**, or **COMMENT**.

### 2. 🔬 Deep Check Technical Matrix
Evaluate each of these 5 pillars with a badge (`✅ PASS`, `⚠️ WARNING`, `🚨 FAIL`) and a concise assessment:
1. **Canonical Envelope Protocol Compatibility**: Check for breaking schema changes, Pydantic V2 compatibility, and monotonic sequencing.
2. **Concurrency, Race Conditions & Deadlocks**: Check async task lifecycles, event loop blocks, background task cancellation.
3. **Sockets, Streaming & Resource Cleanup**: Verify WebSockets, HTTP clients, and subprocesses are closed in `finally:` blocks.
4. **Hardware Telemetry & Fallback Matrix**: Ensure graceful handling when `nvidia-smi` or GPU drivers are unavailable.
5. **Zero-Trust Security & Credential Hygiene**: Ensure strict `SecretMasker` usage and sanitized inputs.

### 3. ❌ What Is Wrong & Why
For every issue found:
- Specify the file and line number.
- Explain clearly **what is wrong** and **why it causes a failure or vulnerability** under distributed edge mesh conditions.
- Assign severity: `🚨 Critical`, `⚠️ High`, `💡 Medium`, or `ℹ️ Low`.

### 4. 🛠️ What Is Needed & How to Fix
For each identified issue:
- Explain **what is needed** to resolve it properly.
- Provide a concrete, ready-to-commit code suggestion using GitHub markdown:
```suggestion
# Corrected code snippet
```
- Specify any missing unit tests or regression cases required in `tests/`.

### 5. 📋 Author Action Checklist
Bulleted checklist of tasks the PR author must complete before merge.
"""

DEEP_CHECK_ADDENDUM = """
## 🔬 MANDATORY DEEP CHECK AUDIT (ENABLED):
Execute an exhaustive audit of all edge cases:
- Probe for async socket leaks during unexpected WebSocket disconnects.
- Verify that streaming generators do not stall if a consumer stops reading.
- Validate that protocol sequence re-ordering attacks cannot bypass message validation.
- Verify that error responses in inference adapters conform to `JobErrorPayload`.
"""

SCORE_INSTRUCTIONS = """
### 6. 🏆 Code Quality & Architectural Readiness Score
Calculate and output an objective numerical production-readiness score from 0 to 100:
**Overall Score: [Score] / 100**

Provide a strict, transparent point breakdown (0 to 20 points for each category):
- **Protocol Adherence & Schema Safety**: [X]/20 (Pydantic V2 validation, envelope invariants, strict forbid)
- **Concurrency & Async Integrity**: [X]/20 (Thread safety, locks on shared metrics/dicts, non-blocking event loop)
- **Resource Lifecycle & Socket Safety**: [X]/20 (Process cleanup, timeouts, WebSocket connection safety)
- **Hardware Telemetry & Fallback Robustness**: [X]/20 (Graceful parsing of non-numeric hardware data, zero division guards)
- **Code Cleanliness & Zero-Trust Security**: [X]/20 (No hardcoded credentials, secret masking, docstrings, type hints)

*Score Verdict*: Provide a 1-sentence scoring rationale and production-readiness summary.
"""


def get_git_diff(base_branch: str = "main", head_ref: str = "HEAD") -> str:
    """Retrieve git diff between base and head."""
    cmd = ["git", "diff", f"{base_branch}...{head_ref}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout
    except subprocess.CalledProcessError as e:
        cmd = ["git", "diff", base_branch]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout
        raise RuntimeError(f"Failed to get git diff: {e.stderr}")


async def fetch_pr_diff_from_github(repo: str, pr_number: str, token: str) -> str:
    """Fetch unified diff for a Pull Request directly from GitHub API."""
    import httpx

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "Antigravity-Review-Agent",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


async def post_review_to_github(repo: str, pr_number: str, token: str, review_body: str, event: str = "COMMENT") -> None:
    """Post review comment directly to the GitHub Pull Request."""
    import httpx

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Antigravity-Review-Agent",
    }
    payload = {
        "body": review_body,
        "event": event,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code in (200, 201):
            print(f"Successfully posted PR review to {repo}#{pr_number}!")
            return

        # Fallback to issue comment if PR review API is restricted or author equals token owner
        fallback_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        fb_response = await client.post(fallback_url, headers=headers, json={"body": review_body})
        if fb_response.status_code in (200, 201):
            print(f"Successfully posted review as PR comment to {repo}#{pr_number}!")
        else:
            print(f"Warning: Failed to post to GitHub ({response.status_code}): {response.text}")


async def run_antigravity_agent(prompt: str, system_instructions: str, model: str = "gemini-2.5-flash") -> str:
    """Execute review using direct API or Google Antigravity SDK with timeout failover."""
    api_key = os.environ.get("ANTIGRAVITY_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "Missing API Key. Please set ANTIGRAVITY_API_KEY or GEMINI_API_KEY environment variable.\n"
            "Get one at: https://aistudio.google.com/app/api-keys"
        )

    # In CI/GitHub Actions, use high-speed direct API to avoid headless IPC container deadlocks
    if os.environ.get("CI") == "true":
        print("Running in CI mode: Using high-speed Gemini Agent API...")
        return await run_gemini_fallback(prompt, system_instructions, api_key, model)

    try:
        from google.antigravity import Agent, LocalAgentConfig
        print("Using Google Antigravity SDK runtime...")
        config = LocalAgentConfig(
            api_key=api_key,
            model=model,
            system_instructions=system_instructions,
            workspaces=[os.getcwd()],
        )

        async def _call_agent():
            async with Agent(config) as agent:
                response = await agent.chat(prompt)
                output_tokens = []
                async for token in response:
                    sys.stdout.write(token)
                    sys.stdout.flush()
                    output_tokens.append(token)
                return "".join(output_tokens)

        # 25-second watchdog for local harness
        return await asyncio.wait_for(_call_agent(), timeout=25.0)
    except Exception as e:
        print(f"Notice: Antigravity SDK harness encountered ({e}). Transitioning to direct API with multi-model failover...")
        return await run_gemini_fallback(prompt, system_instructions, api_key, model)


async def run_gemini_fallback(prompt: str, system_instructions: str, api_key: str, initial_model: str) -> str:
    """Fallback using httpx to call Gemini API directly with retry and model fallback."""
    import httpx

    models_to_try = [initial_model]
    for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if m not in models_to_try:
            models_to_try.append(m)

    last_error = None
    for model in models_to_try:
        for attempt in range(1, 4):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "system_instruction": {"parts": [{"text": system_instructions}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 8192,
                    },
                }

                print(f"Connecting with model '{model}' (attempt {attempt}/3)...")
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(url, json=payload)
                    if response.status_code in (429, 503):
                        print(f"Model '{model}' returned HTTP {response.status_code} (capacity limit). Backing off {attempt * 2}s...")
                        await asyncio.sleep(attempt * 2)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    print(text)
                    return text
            except Exception as err:
                last_error = err
                print(f"Notice on '{model}' attempt {attempt}: {err}")
                await asyncio.sleep(2)

    raise RuntimeError(f"All model attempts exhausted. Last error: {last_error}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity PR Review & Deep Check for Viento SDK")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="GitHub repo (owner/repo)")
    parser.add_argument("--pr", default=os.environ.get("GITHUB_PR_NUMBER") or os.environ.get("PULL_REQUEST_NUMBER", ""), help="Pull Request number")
    parser.add_argument("--base", default="main", help="Base branch (default: main)")
    parser.add_argument("--head", default="HEAD", help="Head commit or branch (default: HEAD)")
    parser.add_argument("--diff-file", help="Path to pre-extracted diff file instead of git")
    parser.add_argument("--deep", action="store_true", help="Execute deep architectural & safety audit")
    parser.add_argument("--score", action="store_true", default=True, help="Include detailed 0-100 Code Quality & Architectural Readiness Score")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model identifier (default: gemini-2.5-flash)")
    parser.add_argument("--output", help="Path to write markdown output report")
    parser.add_argument("--post-comment", action="store_true", help="Post review comment directly to GitHub PR")
    parser.add_argument("--additional-context", default="", help="Custom instructions or review focus")

    args = parser.parse_args()

    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")

    # Obtain diff: either from GitHub API, file, or git
    diff_text = ""
    if args.repo and args.pr and github_token:
        print(f"Fetching diff for PR #{args.pr} from GitHub repository '{args.repo}'...")
        try:
            diff_text = await fetch_pr_diff_from_github(args.repo, args.pr, github_token)
        except Exception as e:
            print(f"Warning: Failed to fetch diff via GitHub API: {e}. Falling back to git diff.")

    if not diff_text:
        if args.diff_file:
            with open(args.diff_file, "r", encoding="utf-8") as f:
                diff_text = f.read()
        else:
            diff_text = get_git_diff(args.base, args.head)

    if not diff_text.strip():
        print(f"No changes detected between {args.base} and {args.head}. Review skipped.")
        sys.exit(0)

    # Construct instructions & prompt
    system_instructions = VIENTO_REVIEW_INSTRUCTIONS
    if args.deep:
        system_instructions += DEEP_CHECK_ADDENDUM
    if args.score:
        system_instructions += SCORE_INSTRUCTIONS

    user_prompt = f"Please perform a full review and deep check of the following PR code diff for Viento SDK:\n\n```diff\n{diff_text}\n```\n"
    if args.additional_context:
        user_prompt += f"\n\nAdditional user instructions:\n{args.additional_context}\n"

    mode_label = "🔬 Deep Check & Full Analysis" if args.deep else "Standard PR Review"
    print(f"=== Antigravity PR Review Agent: {mode_label} ===")
    print(f"Diff length: {len(diff_text)} chars")
    print("Running analysis...\n")

    review_result = await run_antigravity_agent(user_prompt, system_instructions, model=args.model)

    # Save to file if requested
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(review_result)
        print(f"\nReview report successfully saved to: {args.output}")

    # Post comment to GitHub PR if requested
    if args.post_comment and args.repo and args.pr:
        if not github_token:
            print("Warning: Cannot post review to GitHub: GITHUB_TOKEN environment variable is missing.")
        else:
            print(f"\nPosting review comment to GitHub PR #{args.pr}...")
            # Detect verdict from review text
            event = "COMMENT"
            if "REQUEST_CHANGES" in review_result:
                event = "REQUEST_CHANGES"
            elif "APPROVE" in review_result and "🚨 FAIL" not in review_result:
                event = "APPROVE"

            await post_review_to_github(args.repo, args.pr, github_token, review_result, event=event)


if __name__ == "__main__":
    asyncio.run(main())
