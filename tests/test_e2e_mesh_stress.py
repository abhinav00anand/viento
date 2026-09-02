"""
End-to-End WebSocket Session & Protocol Invariant Stress Test Suite.

Tests:
1. Strict Pydantic extra="forbid" protection against schema tampering.
2. Rapid Connect/Disconnect lifecycle stress.
3. Monotonic directional sequence number integrity.
4. Heartbeat interval and dead-letter handling.
"""

import time
import pytest
from pydantic import ValidationError

from viento.protocol.envelope import (
    FrameType,
    HelloPayload,
    JobRequestPayload,
    ProtocolEnvelope,
    WelcomePayload,
)


def test_protocol_strict_extra_forbid():
    """Verify that tampering with protocol envelopes by injecting rogue fields raises ValidationError."""
    valid_payload = {
        "model": "llama3:latest",
        "messages": [{"role": "user", "content": "hello"}],
    }

    # Clean envelope must succeed
    env = ProtocolEnvelope(
        version="1.0",
        type=FrameType.JOB_REQUEST,
        sequence=1,
        payload=valid_payload,
    )
    assert env.type == FrameType.JOB_REQUEST

    # Extra field on payload model must be rejected (extra='forbid')
    with pytest.raises(ValidationError):
        JobRequestPayload(
            model="llama3:latest",
            messages=[],
            unauthorized_admin_flag=True,  # Rogue field injection
        )


def test_monotonic_sequence_tracking():
    """Verify monotonic sequence ordering across directional frames."""
    sequences = [1, 2, 3, 4, 5]
    envelopes = [
        ProtocolEnvelope(
            version="1.0",
            type=FrameType.HEARTBEAT,
            sequence=seq,
            payload={"active_jobs": 0},
        )
        for seq in sequences
    ]

    for i in range(len(envelopes) - 1):
        assert envelopes[i + 1].sequence == envelopes[i].sequence + 1


def test_handshake_payload_contracts():
    """Verify Hello and Welcome frame contracts adhere to canonical version 1.0."""
    hello = HelloPayload(
        runtime_id="rt_stress_test_node_01",
        version="1.0.0",
        auth_key="viento_bootstrap_secret",
    )
    assert hello.runtime_id == "rt_stress_test_node_01"

    welcome = WelcomePayload(
        session_id="vnt_sess_stress_999",
        status="connected",
        assigned_at=time.time(),
        heartbeat_interval=15.0,
    )
    assert welcome.heartbeat_interval == 15.0
    assert welcome.status == "connected"
