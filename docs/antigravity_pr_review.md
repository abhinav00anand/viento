# 🤖 Antigravity PR Review & Deep Check Agent for Zephyr SDK

The **Zephyr SDK** integrates Google Antigravity as an automated Pull Request (PR) code review agent. Powered by the Google Antigravity SDK (`google-antigravity`) and Gemini models, the agent automatically evaluates pull requests, enforces architectural invariants, details **what is wrong** and **what is needed** with concrete code suggestions, and posts structured comments directly onto GitHub Pull Requests.

---

## Table of Contents

1. [Key Capabilities](#key-capabilities)
2. [Review Feedback Structure](#review-feedback-structure)
3. [Prerequisites & Repository Secrets](#prerequisites--repository-secrets)
4. [Review Triggers & Usage](#review-triggers--usage)
   - [Automated PR Reviews](#1-automated-pr-reviews)
   - [On-Demand Review Comments](#2-on-demand-review-comments)
   - [Deep Check Audit](#3-deep-check-audit)
   - [Manual Workflow Dispatch](#4-manual-workflow-dispatch)
5. [The 5 Pillars of the Deep Check](#the-5-pillars-of-the-deep-check)
6. [Running Local Reviews (Dry-Run)](#running-local-reviews-dry-run)
7. [Severity Levels](#severity-levels)

---

## Key Capabilities

- **Deep Architectural Grounding**: Specifically tuned for Zephyr's Canonical Envelope Protocol (V1.0), `InferenceBackend` lifecycle, and zero token drop backpressure queueing.
- **Direct GitHub PR Commenting**: Posts full reviews and comments directly to the GitHub Pull Request conversation via the GitHub API.
- **Actionable Remediation**: Explicitly highlights **what is wrong & why** (with file and line references) and provides **what is needed** (complete, copy-pasteable ````suggestion```` blocks).
- **5-Pillar Deep Check**: Thoroughly investigates backwards compatibility, async task concurrency, socket lifecycles, telemetry fallback, and zero-trust credential hygiene.

---

## Review Feedback Structure

Every Antigravity review posted to a Pull Request contains:

1. **📊 Executive Summary & Verdict**: High-level overview of the PR changes and final recommendation (`APPROVE`, `REQUEST_CHANGES`, or `COMMENT`).
2. **🔬 Deep Check Technical Matrix**: Pass/Warning/Fail scorecard across all 5 architectural pillars.
3. **❌ What Is Wrong & Why**: Concrete breakdown of bugs, race conditions, edge case failures, or style deviations.
4. **🛠️ What Is Needed & How to Fix**: Exact remediation steps, missing unit tests in `tests/`, and GitHub-native ````suggestion```` code blocks.
5. **📋 Author Action Checklist**: Clear list of items the author must address before merging.

---

## Prerequisites & Repository Secrets

To enable Antigravity reviews in GitHub Actions:

1. Obtain an API key from **[Google AI Studio](https://aistudio.google.com/app/api-keys)**.
2. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.
4. Name the secret `ANTIGRAVITY_API_KEY` (or `GEMINI_API_KEY`) and paste your API key.

---

## Review Triggers & Usage

### 1. Automated PR Reviews
Whenever a Pull Request is opened, reopened, or updated with new commits against `main`, the Antigravity review workflow runs automatically with the Deep Check enabled.

### 2. On-Demand Review Comments
Collaborators or maintainers can trigger a review at any time by commenting on a Pull Request:
```markdown
@agy /review
```

### 3. Deep Check Audit
To specifically request a deep audit focused on protocol invariants, async concurrency, and resource cleanup, comment:
```markdown
@agy /deepcheck
```
*You can also include custom focus instructions:*
```markdown
@agy /deepcheck focus on connection manager reconnect loop and task cancellation
```

### 4. Manual Workflow Dispatch
From the GitHub repository:
1. Go to the **Actions** tab.
2. Select **🤖 Antigravity PR Review & Deep Check**.
3. Click **Run workflow**.
4. (Optional) Provide the PR number, check **Perform deep architectural, concurrency, and protocol invariant audit**, and click **Run**.

---

## The 5 Pillars of the Deep Check

| Pillar | Focus Areas |
| :--- | :--- |
| **1. Protocol Compatibility** | Verifies that changes to `viento/protocol/` preserve Pydantic V2 `extra="forbid"` and do not break compatibility with older edge nodes or the Cloud Control Plane. |
| **2. Concurrency & Deadlocks** | Audits async tasks, `asyncio.Queue`, `asyncio.Event`, and locks in `viento/connection/` and `viento/scheduler/` for deadlocks, race conditions, or unhandled task exceptions. |
| **3. Sockets & Resource Leaks** | Verifies that WebSocket connections, HTTP client sessions (`httpx.AsyncClient`), and background threads are closed gracefully in `finally:` blocks during disconnects. |
| **4. Hardware Telemetry Fallback** | Ensures `viento/telemetry/` gracefully falls back to CPU metrics when `nvidia-smi` is absent, without raising unhandled exceptions in the node daemon. |
| **5. Zero-Trust Security** | Checks for hardcoded credentials (enforcing `SecretMasker`), unsanitized inputs, and command injection vectors. |

---

## Running Local Reviews (Dry-Run)

You can run the review agent locally on your current Git branch before pushing or opening a PR using the standalone script:

```bash
# Set your API key
export ANTIGRAVITY_API_KEY="your-gemini-api-key"
# On Windows PowerShell:
# $env:ANTIGRAVITY_API_KEY="your-gemini-api-key"

# Standard review against main
python scripts/review_agent.py --base main --head HEAD

# Deep check review saved to markdown report
python scripts/review_agent.py --base main --head HEAD --deep --output review_report.md

# Review a remote PR and post review comment directly to GitHub
python scripts/review_agent.py --repo abhinav00anand/zephyr --pr 1 --deep --post-comment
```

---

## Severity Levels

The agent classifies feedback using standardized severity badges:

- 🚨 **Critical**: Breaking protocol changes without migration, security flaws, unhandled deadlocks, or token corruption. Must be resolved before merge.
- ⚠️ **High**: Memory leaks, unclosed sockets, missing async error handlers, or race conditions.
- 💡 **Medium**: Deviations from style guidelines, missing docstrings, inconsistent exceptions, or missing unit test coverage.
- ℹ️ **Low**: Minor typos, cosmetic formatting adjustments, or non-blocking refactoring suggestions.
