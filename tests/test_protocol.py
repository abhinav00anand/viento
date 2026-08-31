"""Unit tests for Zephyr protocol envelopes, serialization, validation, and sequence tracking."""

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
from viento.protocol.validator import (
    SequenceTracker,
)


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
