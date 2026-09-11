import uuid

import pytest

from viento.protocol.envelope import Envelope


def test_envelope_generates_valid_uuid():
    """Ensure that an Envelope instance receives a valid UUID string as its id."""
    payload = {"message": "test"}
    env = Envelope(payload=payload)

    # The id should be a string
    assert isinstance(env.id, str)

    # It should be a valid UUID4 string
    try:
        parsed = uuid.UUID(env.id, version=4)
    except Exception:
        pytest.fail(f"Envelope id is not a valid UUID4: {env.id}")
    else:
        # Ensure the parsed UUID matches the string representation
        assert str(parsed) == env.id

    # Payload should be preserved
    assert env.payload == payload
