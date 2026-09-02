# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | ✅ Active          |
| 0.1.x   | ❌ End of Life     |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email **indrohelpdesk@gmail.com** with:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

We will acknowledge your report within **48 hours** and aim to release a fix within **7 days** for critical issues.

## Security Design Principles

1. **No secrets on disk:** API keys (`vnt_tmp_...`) are held only in process memory and stripped from all disk writes.
2. **TLS-only connections:** All cloud gateway connections use `wss://` (WebSocket Secure). Plaintext `ws://` is only permitted for localhost testing.
3. **Secret masking in logs:** The `SecretMasker` automatically redacts API key patterns from all structured log output.
4. **Sequence validation:** `SequenceTracker` detects replay attacks and out-of-order frames on both connection directions.
5. **Input validation:** All wire frames are validated through Pydantic V2 strict models before processing.
