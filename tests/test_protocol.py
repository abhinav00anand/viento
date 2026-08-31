"""Unit tests for Zephyr protocol envelopes, serialization, validation, and sequence tracking."""

import json

import pytest
from pydantic import SecretStr

from viento.connection.manager import ConnectionManager
from viento.protocol.envelope import (
    CancelAckPayload,
    CancelJobPayload,
    EmbeddingRequestPayload,
    EmbeddingResponsePayload,
    FrameType,
    HardwareSpecs,
    HeartbeatPayload,
    HelloPayload,
    JobAckPayload,
    JobCompletePayload,
    JobErrorPayload,
    JobRequestPayload,
    ProtocolEnvelope,
    RegisterPayload,
    SessionReadyPayload,
    TokenChunkPayload,
    WelcomePayload,
)
from viento.protocol.validator import SequenceError, SequenceTracker


def test_hello_payload_instantiation():
    payload = HelloPayload(runtime_id="client-123", version="1.0.0")
    assert payload.runtime_id == "client-123"
    assert payload.version == "1.0.0"


def test_welcome_payload_instantiation():
    payload = WelcomePayload(session_id="sess-456", assigned_at=100.0)
    assert payload.session_id == "sess-456"
    assert payload.heartbeat_interval == 15.0


def test_register_payload_instantiation():
    payload = RegisterPayload(
        runtime_name="worker-01",
        hardware=HardwareSpecs(cpu_count=8, ram_total_mb=16384),
        supported_models=["llama3"],
    )
    assert payload.runtime_name == "worker-01"
    assert payload.supported_models == ["llama3"]


def test_ready_payload_instantiation():
    payload = SessionReadyPayload(session_id="sess-01", api_key="zph_tmp_123", expires_at=1000.0)
    assert payload.session_id == "sess-01"
    assert payload.api_key == "zph_tmp_123"


def test_heartbeat_payload_instantiation():
    payload = HeartbeatPayload(active_jobs=2)
    assert payload.active_jobs == 2


def test_job_request_payload_instantiation():
    payload = JobRequestPayload(
        model="llama3", messages=[{"role": "user", "content": "Hello world"}], temperature=0.8
    )
    assert payload.model == "llama3"
    assert payload.messages[0]["content"] == "Hello world"
    assert payload.temperature == 0.8


def test_job_ack_payload_instantiation():
    payload = JobAckPayload(status="accepted", queue_position=0)
    assert payload.status == "accepted"


def test_token_chunk_payload_instantiation():
    payload = TokenChunkPayload(delta="Hello", index=0)
    assert payload.delta == "Hello"
    assert payload.index == 0


def test_job_complete_payload_instantiation():
    payload = JobCompletePayload(finish_reason="stop", total_tokens=5)
    assert payload.finish_reason == "stop"
    assert payload.total_tokens == 5


def test_job_error_payload_instantiation():
    payload = JobErrorPayload(
        error_message="Model llama99 not loaded", error_code="MODEL_NOT_FOUND"
    )
    assert payload.error_code == "MODEL_NOT_FOUND"


def test_cancel_job_payload_instantiation():
    payload = CancelJobPayload(reason="User cancelled request")
    assert payload.reason == "User cancelled request"


def test_cancel_ack_payload_instantiation():
    payload = CancelAckPayload(status="cancelled")
    assert payload.status == "cancelled"


def test_embedding_request_payload_instantiation():
    payload = EmbeddingRequestPayload(model="all-minilm", input=["text 1", "text 2"])
    assert payload.model == "all-minilm"
    assert len(payload.input) == 2


def test_embedding_response_payload_instantiation():
    payload = EmbeddingResponsePayload(
        model="all-minilm",
        embeddings=[[0.1, 0.2, 0.3]],
        total_tokens=5,
    )
    assert payload.total_tokens == 5
    assert len(payload.embeddings) == 1


def test_envelope_serialization_and_deserialization_roundtrip():
    payload = JobRequestPayload(
        model="mistral", messages=[{"role": "user", "content": "Write a poem"}]
    )
    envelope = ProtocolEnvelope(
        type=FrameType.JOB_REQUEST,
        session_id="client-01",
        sequence=1,
        payload=payload.model_dump(),
    )

    serialized_json = envelope.to_json()
    assert isinstance(serialized_json, str)
    assert "mistral" in serialized_json

    deserialized = ProtocolEnvelope.from_json(serialized_json)
    assert deserialized.type == FrameType.JOB_REQUEST
    assert deserialized.session_id == "client-01"
    assert deserialized.sequence == 1
    assert deserialized.payload["model"] == "mistral"


def test_secret_credentials_are_typed_and_masked():
    secret = "super-secret-key"
    hello = HelloPayload(runtime_id="client-123", auth_key=secret)
    ready = SessionReadyPayload(session_id="sess-01", api_key=secret, expires_at=1000.0)

    assert isinstance(hello.auth_key, SecretStr)
    assert isinstance(ready.api_key, SecretStr)

    assert secret not in repr(hello)
    assert secret not in str(hello)
    assert secret not in hello.model_dump_json()
    assert "**********" in hello.model_dump_json()

    assert secret not in repr(ready)
    assert secret not in str(ready)
    assert secret not in ready.model_dump_json()
    assert "**********" in ready.model_dump_json()


def test_secret_credentials_are_unwrapped_only_at_wire_boundary():
    secret = "wire-secret-key"
    payload = HelloPayload(runtime_id="client-123", auth_key=secret)
    envelope = ProtocolEnvelope(
        type=FrameType.HELLO,
        sequence=0,
        payload=payload.model_dump(),
    )

    in_memory_dump = envelope.model_dump()
    assert isinstance(in_memory_dump["payload"]["auth_key"], SecretStr)
    assert secret not in repr(in_memory_dump)

    wire = envelope.to_json()
    assert secret in wire
    assert "**********" not in wire

    decoded = json.loads(wire)
    assert decoded["payload"]["auth_key"] == secret

    roundtrip = ProtocolEnvelope.from_json(wire)
    roundtrip_payload = HelloPayload.model_validate(roundtrip.payload)
    assert roundtrip_payload.auth_key.get_secret_value() == secret


def test_session_ready_payload_parses_secret_key():
    secret = "ready-secret-key"
    payload = SessionReadyPayload(
        session_id="sess-01",
        api_key=secret,
        expires_at=1000.0,
        ttl_seconds=900,
    )

    assert payload.api_key.get_secret_value() == secret
    assert payload.ttl_seconds == 900


def test_sequence_tracker_normal_flow():
    tracker = SequenceTracker(strict=True)
    session = "sess-001"

    valid, err = tracker.track(session, 0)
    assert valid is True and err is None

    valid, err = tracker.track(session, 1)
    assert valid is True and err is None

    valid, err = tracker.track(session, 2)
    assert valid is True and err is None
    assert tracker.get_last_sequence(session) == 2


def test_sequence_tracker_rejects_duplicate_and_gap_in_strict_mode():
    tracker = SequenceTracker(strict=True)
    session = "sess-001"
    tracker.track(session, 0)

    with pytest.raises(SequenceError):
        tracker.track(session, 0)

    with pytest.raises(SequenceError):
        tracker.track(session, 2)


def test_connection_sequence_state_survives_reconnect_for_same_session():
    manager = object.__new__(ConnectionManager)
    manager.next_outgoing_sequence = 0
    manager.expected_incoming_sequence = 0
    manager._sequence_session_id = None
    manager._sequence_state_initialized = False

    manager._sync_sequence_session("sess-001")
    manager.next_outgoing_sequence = 8
    manager.expected_incoming_sequence = 11

    manager._sync_sequence_session("sess-001")

    assert manager.next_outgoing_sequence == 8
    assert manager.expected_incoming_sequence == 11
    assert manager._sequence_session_id == "sess-001"


def test_connection_sequence_state_resets_only_for_new_session():
    manager = object.__new__(ConnectionManager)
    manager.next_outgoing_sequence = 7
    manager.expected_incoming_sequence = 9
    manager._sequence_session_id = "sess-old"
    manager._sequence_state_initialized = True

    manager._sync_sequence_session("sess-new")

    assert manager.next_outgoing_sequence == 0
    assert manager.expected_incoming_sequence == 0
    assert manager._sequence_session_id == "sess-new"


def test_new_session_welcome_requires_sequence_zero():
    manager = object.__new__(ConnectionManager)
    manager.is_connected = True

    envelope = ProtocolEnvelope(
        type=FrameType.WELCOME,
        session_id="sess-new",
        sequence=1,
        payload={"session_id": "sess-new", "assigned_at": 1.0},
    )

    assert manager._validate_welcome_sequence(envelope, None) is False
    assert manager.is_connected is False


def test_new_session_welcome_sequence_zero_is_accepted():
    manager = object.__new__(ConnectionManager)
    manager.is_connected = True

    envelope = ProtocolEnvelope(
        type=FrameType.WELCOME,
        session_id="sess-new",
        sequence=0,
        payload={"session_id": "sess-new", "assigned_at": 1.0},
    )

    assert manager._validate_welcome_sequence(envelope, None) is True
    assert manager.is_connected is True


def test_resumed_session_welcome_must_continue_expected_sequence():
    manager = object.__new__(ConnectionManager)
    manager.is_connected = True
    manager.expected_incoming_sequence = 7

    valid = ProtocolEnvelope(
        type=FrameType.WELCOME,
        session_id="sess-existing",
        sequence=7,
        payload={"session_id": "sess-existing", "assigned_at": 1.0},
    )
    invalid = ProtocolEnvelope(
        type=FrameType.WELCOME,
        session_id="sess-existing",
        sequence=8,
        payload={"session_id": "sess-existing", "assigned_at": 1.0},
    )

    assert manager._validate_welcome_sequence(valid, "sess-existing") is True
    assert manager._validate_welcome_sequence(invalid, "sess-existing") is False
    assert manager.is_connected is False


def test_incoming_sequence_rejects_wrong_session():
    manager = object.__new__(ConnectionManager)
    manager.session_id = "sess-001"
    manager.expected_incoming_sequence = 0
    manager.is_connected = True

    envelope = ProtocolEnvelope(
        type=FrameType.HEARTBEAT_ACK,
        session_id="sess-other",
        sequence=0,
        payload={"timestamp": 1.0},
    )

    assert manager._validate_incoming_sequence(envelope) is False
    assert manager.is_connected is False
