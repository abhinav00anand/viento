"""
Canonical Wire Protocol Envelope (Version 1.0) for Viento SDK.
Maintains byte-for-byte schema parity with Cloud Control Plane protocol definitions.
"""

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class FrameType(str, Enum):
    """Supported WebSocket canonical frame types."""

    HELLO = "hello"
    WELCOME = "welcome"
    REGISTER = "register"
    REGISTER_ACK = "register_ack"
    SESSION_READY = "session_ready"
    JOB_REQUEST = "job_request"
    JOB_ACK = "job_ack"
    TOKEN_CHUNK = "token_chunk"
    JOB_COMPLETE = "job_complete"
    JOB_ERROR = "job_error"
    CANCEL_JOB = "cancel_job"
    CANCEL_ACK = "cancel_ack"
    EMBEDDING_REQUEST = "embedding_request"
    EMBEDDING_RESPONSE = "embedding_response"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    DISCONNECT = "disconnect"


MessageType = FrameType


class ModelInfo(BaseModel):
    """Detailed model metadata and capability specification."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: str = "ready"
    backend: str = "ollama"
    context_length: int = 8192
    max_output_tokens: int = 4096
    quantization: str = "unknown"
    capabilities: List[str] = Field(default_factory=lambda: ["chat", "streaming"])
    max_concurrency: int = 2
    active_jobs: int = 0


class HardwareSpecs(BaseModel):
    """Hardware capability specification reported by runtime. Defaults to unknown if telemetry fails."""

    model_config = ConfigDict(extra="forbid")

    cpu_count: int = 0
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    gpu_name: str = "unknown"
    vram_total_mb: int = 0
    vram_used_mb: int = 0
    device_count: int = 0
    max_sequence_length: int = 4096


class ProtocolEnvelope(BaseModel):
    """
    Canonical Wire Protocol Envelope (Version 1.0).
    Wraps outer metadata (ids, sequence, timestamps) and nested payload.
    Strict validation forbids unknown extra fields.

    SecretStr values are retained in-memory so accidental model/log
    representations remain masked. ``to_json`` is the explicit transport
    boundary and unwraps secrets only when serializing to the wire.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = "1.0"
    type: FrameType
    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    sequence: int = 0
    timestamp: float = Field(default_factory=time.time)
    request_id: Optional[str] = None
    job_id: Optional[str] = None
    session_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    @property
    def msg_type(self) -> FrameType:
        """Backward-compatibility property for legacy validator references."""
        return self.type

    @staticmethod
    def _unwrap_secrets(value: Any) -> Any:
        """Recursively unwrap SecretStr values at the explicit wire boundary."""
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        if isinstance(value, dict):
            return {key: ProtocolEnvelope._unwrap_secrets(item) for key, item in value.items()}
        if isinstance(value, list):
            return [ProtocolEnvelope._unwrap_secrets(item) for item in value]
        if isinstance(value, tuple):
            return [ProtocolEnvelope._unwrap_secrets(item) for item in value]
        return value

    def to_json(self) -> str:
        """Serialize the canonical wire representation, restoring secrets for transport only."""
        data = self.model_dump(exclude_none=True, mode="python")
        return json.dumps(
            self._unwrap_secrets(data),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def validate_payload(self) -> Any:
        """Validate payload dict against expected schema for FrameType if registered."""
        payload_cls = PAYLOAD_TYPE_MAP.get(self.type)
        if payload_cls and isinstance(self.payload, dict):
            return payload_cls.model_validate(self.payload)
        return self.payload

    @classmethod
    def from_json(cls, raw: str) -> "ProtocolEnvelope":
        data = json.loads(raw)
        envelope = cls.model_validate(data)
        envelope.validate_payload()
        return envelope


# Payload Models
class HelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: str
    version: str = "1.0.0"
    auth_key: Optional[SecretStr] = None
    session_id: Optional[str] = None


class WelcomePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: str = "connected"
    assigned_at: float
    heartbeat_interval: float = 15.0


class RegisterPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str
    hardware: HardwareSpecs
    models: List[ModelInfo] = Field(default_factory=list)
    supported_models: List[str] = Field(default_factory=list)


class RegisterAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "registered"
    registered_models: List[str] = Field(default_factory=list)


class SessionReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    api_key: SecretStr
    expires_at: float
    ttl_seconds: int = 3600


ReadyPayload = SessionReadyPayload


class JobRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: List[Dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 512
    top_p: float = 1.0
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    user: Optional[str] = None
    stream: bool = True


class JobAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "accepted"
    queue_position: int = 0


class TokenChunkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta: str
    index: int = 0
    finish_reason: Optional[str] = None


class JobCompletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    is_estimated: bool = False


class JobErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_message: str
    error_code: str = "runtime_error"


class EmbeddingRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    input: List[str]


class EmbeddingResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    embeddings: List[List[float]]
    prompt_tokens: int = 0
    total_tokens: int = 0
    is_estimated: bool = False


class CancelJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "client_disconnected"


DisconnectPayload = CancelJobPayload


class CancelAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "cancelled"


class HeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_jobs: int = 0
    metrics: Dict[str, Any] = Field(default_factory=dict)


class HeartbeatAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: float = Field(default_factory=time.time)


PAYLOAD_TYPE_MAP = {
    FrameType.HELLO: HelloPayload,
    FrameType.WELCOME: WelcomePayload,
    FrameType.REGISTER: RegisterPayload,
    FrameType.REGISTER_ACK: RegisterAckPayload,
    FrameType.SESSION_READY: SessionReadyPayload,
    FrameType.JOB_REQUEST: JobRequestPayload,
    FrameType.JOB_ACK: JobAckPayload,
    FrameType.TOKEN_CHUNK: TokenChunkPayload,
    FrameType.JOB_COMPLETE: JobCompletePayload,
    FrameType.JOB_ERROR: JobErrorPayload,
    FrameType.EMBEDDING_REQUEST: EmbeddingRequestPayload,
    FrameType.EMBEDDING_RESPONSE: EmbeddingResponsePayload,
    FrameType.CANCEL_JOB: CancelJobPayload,
    FrameType.CANCEL_ACK: CancelAckPayload,
    FrameType.HEARTBEAT: HeartbeatPayload,
    FrameType.HEARTBEAT_ACK: HeartbeatAckPayload,
}
