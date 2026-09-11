from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


def _generate_uuid() -> str:
    """Generate a string representation of a UUID4.

    Using a helper function keeps the default_factory simple and ensures the
    generated value is a string, matching the declared type of the `id` field.
    """
    return str(uuid.uuid4())


class Envelope(BaseModel):
    """Standard envelope for messages exchanged between Viento components.

    The `id` field uniquely identifies each envelope and is automatically
    generated if not provided.
    """

    id: str = Field(default_factory=_generate_uuid)
    payload: dict

    class Config:
        # Allow arbitrary payload structures while keeping type checking strict.
        arbitrary_types_allowed = True
        extra = "allow"
