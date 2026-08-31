"""Message envelope serialization, validation, sequence tracking, and error mapping."""

import json
import logging
from typing import Any, Dict, Optional, Tuple, Union

from pydantic import BaseModel, ValidationError

from viento.protocol.envelope import (
    PAYLOAD_TYPE_MAP,
    MessageType,
    ProtocolEnvelope,
)

logger = logging.getLogger(__name__)


class ProtocolValidationError(Exception):
    """Base exception for protocol serialization or validation errors."""

    def __init__(
        self,
        message: str,
        code: str = "PROTOCOL_VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class UnknownMessageTypeError(ProtocolValidationError):
    """Raised when an unrecognized message type string is encountered."""

    def __init__(self, msg_type: str):
        super().__init__(
            message=f"Unknown or unsupported message type: '{msg_type}'",
            code="UNKNOWN_MESSAGE_TYPE",
            details={"msg_type": msg_type},
        )


class InvalidPayloadError(ProtocolValidationError):
    """Raised when envelope payload fails Pydantic validation."""

    def __init__(self, msg_type: str, validation_error: ValidationError):
        super().__init__(
            message=f"Payload validation failed for message type '{msg_type}': {validation_error}",
            code="INVALID_PAYLOAD",
            details={"msg_type": msg_type, "errors": validation_error.errors()},
        )


class SequenceError(ProtocolValidationError):
    """Raised when sequence tracker detects gap, out-of-order, or duplicate message."""

    def __init__(self, session_id: str, expected_seq: int, received_seq: int, reason: str):
        super().__init__(
            message=f"Sequence error for session '{session_id}': received {received_seq}, expected {expected_seq} ({reason})",
            code="SEQUENCE_ERROR",
            details={
                "session_id": session_id,
                "expected_seq": expected_seq,
                "received_seq": received_seq,
                "reason": reason,
            },
        )


class SequenceTracker:
    """Monotonic sequence number tracker per session/sender.

    Enforces strictly sequential message ordering and flags duplicates or gaps.
    """

    def __init__(self, strict: bool = True):
        self.strict = strict
        # session_id -> last_seen_sequence_number
        self._sessions: Dict[str, int] = {}

    def track(self, session_id: str, sequence_num: int) -> Tuple[bool, Optional[str]]:
        """Validates and updates sequence number for session_id.

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_description)
        """
        if session_id not in self._sessions:
            # First message seen for session
            self._sessions[session_id] = sequence_num
            return True, None

        last_seq = self._sessions[session_id]

        if sequence_num == last_seq + 1:
            self._sessions[session_id] = sequence_num
            return True, None
        elif sequence_num <= last_seq:
            reason = "duplicate_or_replayed_message"
            if self.strict:
                raise SequenceError(session_id, last_seq + 1, sequence_num, reason)
            return False, reason
        else:
            # sequence_num > last_seq + 1 -> sequence gap
            reason = f"sequence_gap_detected (skipped {sequence_num - last_seq - 1} messages)"
            if self.strict:
                raise SequenceError(session_id, last_seq + 1, sequence_num, reason)
            self._sessions[session_id] = sequence_num
            return False, reason

    def get_last_sequence(self, session_id: str) -> Optional[int]:
        """Returns the last recorded sequence number for session_id."""
        return self._sessions.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """Clears sequence state for a session."""
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        """Clears all session tracking states."""
        self._sessions.clear()


class ProtocolValidator:
    """High-performance serializer, deserializer, and validator for Zephyr Protocol Envelopes."""

    @staticmethod
    def serialize(envelope: ProtocolEnvelope) -> str:
        """Serializes ProtocolEnvelope to JSON string.

        Args:
            envelope: Pydantic ProtocolEnvelope instance.

        Returns:
            JSON string representation.
        """
        try:
            return envelope.model_dump_json()
        except Exception as e:
            raise ProtocolValidationError(
                message=f"Serialization failed: {e}",
                code="SERIALIZATION_ERROR",
            ) from e

    @staticmethod
    def validate_payload(
        msg_type: Union[str, MessageType], raw_payload: Union[Dict[str, Any], BaseModel]
    ) -> BaseModel:
        """Validates raw dictionary or payload instance against payload model for msg_type.

        Args:
            msg_type: String or MessageType enum value.
            raw_payload: Raw dict payload or BaseModel instance.

        Returns:
            Validated Pydantic payload instance.
        """
        if isinstance(msg_type, str):
            try:
                msg_type = MessageType(msg_type)
            except ValueError:
                raise UnknownMessageTypeError(msg_type)

        payload_cls = PAYLOAD_TYPE_MAP.get(msg_type)
        if not payload_cls:
            raise UnknownMessageTypeError(msg_type.value)

        if isinstance(raw_payload, payload_cls):
            return raw_payload

        if isinstance(raw_payload, BaseModel):
            raw_payload = raw_payload.model_dump()

        if not isinstance(raw_payload, dict):
            raise ProtocolValidationError(
                message=f"Payload must be a dictionary or Pydantic model, got {type(raw_payload).__name__}",
                code="INVALID_PAYLOAD_FORMAT",
            )

        try:
            return payload_cls.model_validate(raw_payload)
        except ValidationError as ve:
            raise InvalidPayloadError(msg_type.value, ve) from ve

    @classmethod
    def deserialize(
        cls, raw_data: Union[str, bytes], validate_typed_payload: bool = True
    ) -> ProtocolEnvelope:
        """Deserializes JSON raw text/bytes into a fully validated ProtocolEnvelope.

        Args:
            raw_data: JSON string or bytes.
            validate_typed_payload: If True, validates envelope.payload into specific payload model.

        Returns:
            ProtocolEnvelope instance with validated typed payload.
        """
        try:
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            parsed_json = json.loads(raw_data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ProtocolValidationError(
                message=f"Malformed JSON data: {e}",
                code="INVALID_JSON",
            ) from e

        if not isinstance(parsed_json, dict):
            raise ProtocolValidationError(
                message="Expected top-level JSON object for envelope",
                code="INVALID_ENVELOPE_FORMAT",
            )

        try:
            envelope = ProtocolEnvelope.model_validate(parsed_json)
        except ValidationError as ve:
            raise ProtocolValidationError(
                message=f"Envelope structure validation failed: {ve}",
                code="ENVELOPE_VALIDATION_FAILED",
                details={"errors": ve.errors()},
            ) from ve

        if validate_typed_payload:
            validated_payload = cls.validate_payload(envelope.msg_type, envelope.payload)
            envelope.payload = validated_payload

        return envelope
