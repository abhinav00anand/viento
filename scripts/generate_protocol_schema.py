"""
Protocol Schema Generator Script for Zephyr.

Generates Private/protocol_specs/schemas.json directly from Cloud ProtocolEnvelope model schema
and discriminated payload union mappings. Ensures single-source-of-truth canonical contract definition.
"""

import json
import sys
from pathlib import Path

# Add Cloud to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "Cloud"))

from app.models.protocol import (
    CancelAckPayload,
    CancelJobPayload,
    DisconnectPayload,
    EmbeddingRequestPayload,
    EmbeddingResponsePayload,
    HeartbeatAckPayload,
    HeartbeatPayload,
    HelloPayload,
    JobAckPayload,
    JobCompletePayload,
    JobErrorPayload,
    JobRequestPayload,
    ProtocolEnvelope,
    RegisterAckPayload,
    RegisterPayload,
    SessionReadyPayload,
    TokenChunkPayload,
    WelcomePayload,
)


def main() -> None:
    root = Path(__file__).parent.parent
    output_path = root / "Private" / "protocol_specs" / "schemas.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_schema = ProtocolEnvelope.model_json_schema()

    payload_models = {
        "hello": HelloPayload,
        "welcome": WelcomePayload,
        "register": RegisterPayload,
        "register_ack": RegisterAckPayload,
        "session_ready": SessionReadyPayload,
        "heartbeat": HeartbeatPayload,
        "heartbeat_ack": HeartbeatAckPayload,
        "job_request": JobRequestPayload,
        "job_ack": JobAckPayload,
        "token_chunk": TokenChunkPayload,
        "job_complete": JobCompletePayload,
        "job_error": JobErrorPayload,
        "cancel_job": CancelJobPayload,
        "cancel_ack": CancelAckPayload,
        "embedding_request": EmbeddingRequestPayload,
        "embedding_response": EmbeddingResponsePayload,
        "disconnect": DisconnectPayload,
    }

    definitions = base_schema.get("$defs", {})
    discriminated_schemas = []

    for type_name, model_cls in payload_models.items():
        payload_schema = model_cls.model_json_schema()
        # Merge sub-definitions
        if "$defs" in payload_schema:
            definitions.update(payload_schema["$defs"])
            del payload_schema["$defs"]

        model_ref_name = model_cls.__name__
        definitions[model_ref_name] = payload_schema

        discriminated_schemas.append({
            "type": "object",
            "properties": {
                "type": {"const": type_name},
                "payload": {"$ref": f"#/$defs/{model_ref_name}"},
            },
            "required": ["type", "payload"],
        })

    base_schema["$defs"] = definitions
    base_schema["discriminated_frame_payloads"] = discriminated_schemas

    formatted = json.dumps(base_schema, indent=2)

    output_path.write_text(formatted, encoding="utf-8")
    print(f"[SUCCESS] Generated complete discriminated protocol schema at: {output_path.resolve()}")


if __name__ == "__main__":
    main()
