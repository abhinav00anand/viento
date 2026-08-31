# Sequence/session reconnect note

The runtime keeps sequence counters scoped to the logical Zephyr session. A transient WebSocket reconnect does not reset sequence state. Counters are reset only when the gateway assigns a different `session_id` during the handshake. This prevents a resumed session from reusing sequence numbers while preserving the existing handshake and reconnect flow.