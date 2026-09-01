"""Regression tests for reconnect and logical-session sequence semantics."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import websockets
from pydantic import ValidationError

import viento.connection.manager as connection_manager_module
from viento.connection.manager import ConnectionManager
from viento.protocol.envelope import FrameType, ModelInfo, ProtocolEnvelope


class FakeConfigManager:
    """Minimal runtime-state sink used by connection-manager handshake tests."""

    def __init__(self):
        self.updates = []

    def update_runtime_state(self, **kwargs):
        self.updates.append(kwargs)


class FakeBackend:
    """Deterministic duck-typed backend dependency for constructor-level setup."""

    def name(self):
        return "test"

    def capabilities(self):
        return ["chat", "streaming"]

    def list_models(self):
        return []


class FakeWebSocket:
    """Deterministic async WebSocket double for handshake and lifecycle tests."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    async def recv(self):
        if not self.frames:
            raise websockets.exceptions.ConnectionClosedOK(None, None)
        return self.frames.pop(0)

    async def send(self, raw):
        decoded = json.loads(raw)
        assert isinstance(decoded, dict)
        self.sent.append(ProtocolEnvelope.model_validate_json(raw))

    async def close(self):
        self.closed = True


class FakeWebSocketContext:
    """Async context manager mirroring websockets.connect() ownership semantics."""

    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        await self.websocket.close()
        return False


class FakeTelemetry:
    def get_hardware_snapshot(self):
        return SimpleNamespace(
            cpu_count_logical=8,
            memory_total_bytes=16 * 1024**3,
            memory_used_bytes=4 * 1024**3,
            gpus=[],
        )


def _config():
    return SimpleNamespace(
        node_name="test-node",
        bootstrap_key="bootstrap-secret",
        max_concurrency=2,
        server_url="wss://example.invalid/ws",
        ollama_url="http://localhost:11434",
        heartbeat_interval=15.0,
    )


def _manager(ws, *, session_id=None, outgoing=0, incoming=0):
    """Build a real ConnectionManager with deterministic injected dependencies."""
    manager = ConnectionManager(
        config=_config(),
        config_manager=FakeConfigManager(),
        backend=FakeBackend(),
    )
    manager.telemetry = FakeTelemetry()
    manager.ws = ws
    manager.is_connected = True
    manager.is_running = True
    manager.session_id = session_id
    manager.next_outgoing_sequence = outgoing
    manager.expected_incoming_sequence = incoming
    manager._sequence_session_id = session_id
    manager._sequence_state_initialized = session_id is not None
    return manager


def _frame(frame_type, session_id, sequence, payload):
    return ProtocolEnvelope(
        type=frame_type,
        session_id=session_id,
        sequence=sequence,
        payload=payload,
    ).to_json()


def _handshake_frames(session_id, *, start_sequence=0, api_key="zph_tmp_test"):
    return [
        _frame(
            FrameType.WELCOME,
            session_id,
            start_sequence,
            {
                "session_id": session_id,
                "assigned_at": 100.0,
                "heartbeat_interval": 15.0,
            },
        ),
        _frame(
            FrameType.REGISTER_ACK,
            session_id,
            start_sequence + 1,
            {"status": "registered", "registered_models": ["llama3"]},
        ),
        _frame(
            FrameType.SESSION_READY,
            session_id,
            start_sequence + 2,
            {
                "session_id": session_id,
                "api_key": api_key,
                "expires_at": 4600.0,
                "ttl_seconds": 3600,
            },
        ),
    ]


def _models():
    return [ModelInfo(id="llama3", name="llama3")]


@pytest.mark.asyncio
async def test_new_logical_session_starts_both_sequence_directions_at_zero():
    ws = FakeWebSocket(_handshake_frames("sess-new"))
    manager = _manager(ws)

    result = await manager._perform_handshake(_models())

    assert result is True
    assert manager.session_id == "sess-new"
    assert manager._sequence_session_id == "sess-new"
    assert manager.next_outgoing_sequence == 1
    assert manager.expected_incoming_sequence == 3
    assert manager.active_api_key == "zph_tmp_test"

    assert [frame.type for frame in ws.sent] == [FrameType.HELLO, FrameType.REGISTER]
    assert [frame.sequence for frame in ws.sent] == [0, 0]
    assert ws.sent[0].session_id is None
    assert ws.sent[1].session_id == "sess-new"


@pytest.mark.asyncio
async def test_resumed_logical_session_preserves_sequence_state_across_transport_reconnect():
    ws = FakeWebSocket(
        _handshake_frames("sess-existing", start_sequence=7, api_key="zph_tmp_rotated")
    )
    manager = _manager(
        ws,
        session_id="sess-existing",
        outgoing=5,
        incoming=7,
    )

    result = await manager._perform_handshake(_models())

    assert result is True
    assert manager.session_id == "sess-existing"
    assert manager._sequence_session_id == "sess-existing"
    assert manager.next_outgoing_sequence == 7
    assert manager.expected_incoming_sequence == 10
    assert manager.active_api_key == "zph_tmp_rotated"

    assert [frame.type for frame in ws.sent] == [FrameType.HELLO, FrameType.REGISTER]
    assert [frame.sequence for frame in ws.sent] == [5, 6]
    assert [frame.session_id for frame in ws.sent] == ["sess-existing", "sess-existing"]


@pytest.mark.asyncio
async def test_session_change_resets_outgoing_and_incoming_sequence_epochs():
    ws = FakeWebSocket(_handshake_frames("sess-new", api_key="zph_tmp_new"))
    manager = _manager(
        ws,
        session_id="sess-old",
        outgoing=42,
        incoming=18,
    )

    result = await manager._perform_handshake(_models())

    assert result is True
    assert manager.session_id == "sess-new"
    assert manager._sequence_session_id == "sess-new"
    assert manager.next_outgoing_sequence == 1
    assert manager.expected_incoming_sequence == 3
    assert [frame.sequence for frame in ws.sent] == [42, 0]
    assert ws.sent[0].session_id == "sess-old"
    assert ws.sent[1].session_id == "sess-new"


@pytest.mark.asyncio
async def test_start_reconnects_same_logical_session_and_closes_each_transport(monkeypatch):
    first_ws = FakeWebSocket(_handshake_frames("sess-initial"))
    second_ws = FakeWebSocket(
        _handshake_frames("sess-initial", start_sequence=3, api_key="zph_tmp_reconnected")
    )
    sockets = [first_ws, second_ws]
    heartbeat_cancelled = asyncio.Event()

    def fake_connect(*args, **kwargs):
        assert args[0] == "wss://example.invalid/ws"
        assert kwargs["max_size"] == 5_242_880
        return FakeWebSocketContext(sockets.pop(0))

    monkeypatch.setattr(connection_manager_module.websockets, "connect", fake_connect)

    manager = ConnectionManager(
        config=_config(),
        config_manager=FakeConfigManager(),
        backend=FakeBackend(),
    )
    manager.telemetry = FakeTelemetry()

    async def fake_heartbeat_loop():
        try:
            await manager._shutdown_event.wait()
        except asyncio.CancelledError:
            heartbeat_cancelled.set()
            raise

    monkeypatch.setattr(manager, "_heartbeat_loop", fake_heartbeat_loop)

    handshake_sessions = []

    def on_handshake(api_key, session_id, ttl):
        handshake_sessions.append((api_key, session_id, ttl))
        if len(handshake_sessions) == 2:
            manager.is_connected = False
            manager.is_running = False
            manager._shutdown_event.set()

    manager.on_handshake_callback = on_handshake

    await manager.start()

    assert sockets == []
    assert handshake_sessions == [
        ("zph_tmp_test", "sess-initial", 3600.0),
        ("zph_tmp_reconnected", "sess-initial", 3600.0),
    ]
    assert first_ws.closed is True
    assert second_ws.closed is True
    assert [frame.type for frame in first_ws.sent] == [FrameType.HELLO, FrameType.REGISTER]
    assert [frame.sequence for frame in first_ws.sent] == [0, 0]
    assert [frame.type for frame in second_ws.sent] == [FrameType.HELLO, FrameType.REGISTER]
    assert [frame.sequence for frame in second_ws.sent] == [1, 2]
    assert manager.session_id == "sess-initial"
    assert manager.next_outgoing_sequence == 3
    assert manager.expected_incoming_sequence == 6
    assert manager.is_connected is False
    assert manager.is_running is False
    assert heartbeat_cancelled.is_set()
    assert manager._heartbeat_task is None


def test_reconnect_welcome_with_invalid_sequence_does_not_mutate_logical_session_state():
    manager = _manager(
        FakeWebSocket([]),
        session_id="sess-existing",
        outgoing=12,
        incoming=9,
    )

    invalid = ProtocolEnvelope(
        type=FrameType.WELCOME,
        session_id="sess-existing",
        sequence=11,
        payload={
            "session_id": "sess-existing",
            "assigned_at": 100.0,
            "heartbeat_interval": 15.0,
        },
    )

    assert manager._validate_welcome_sequence(invalid, "sess-existing") is False
    assert manager.is_connected is False
    assert manager.session_id == "sess-existing"
    assert manager._sequence_session_id == "sess-existing"
    assert manager.next_outgoing_sequence == 12
    assert manager.expected_incoming_sequence == 9


def test_incoming_duplicate_does_not_advance_sequence_tracker():
    manager = _manager(FakeWebSocket([]), session_id="sess-001", incoming=5)

    duplicate = ProtocolEnvelope(
        type=FrameType.HEARTBEAT_ACK,
        session_id="sess-001",
        sequence=4,
        payload={"timestamp": 100.0},
    )

    assert manager._validate_incoming_sequence(duplicate) is False
    assert manager.is_connected is True
    assert manager.expected_incoming_sequence == 5


def test_incoming_sequence_gap_disconnects_before_accepting_out_of_order_frame():
    manager = _manager(FakeWebSocket([]), session_id="sess-001", incoming=5)

    gap = ProtocolEnvelope(
        type=FrameType.HEARTBEAT_ACK,
        session_id="sess-001",
        sequence=7,
        payload={"timestamp": 100.0},
    )

    assert manager._validate_incoming_sequence(gap) is False
    assert manager.is_connected is False
    assert manager.expected_incoming_sequence == 5


def test_incoming_frame_from_previous_or_foreign_session_is_rejected():
    manager = _manager(FakeWebSocket([]), session_id="sess-current", incoming=3)

    foreign = ProtocolEnvelope(
        type=FrameType.HEARTBEAT_ACK,
        session_id="sess-old",
        sequence=3,
        payload={"timestamp": 100.0},
    )

    assert manager._validate_incoming_sequence(foreign) is False
    assert manager.is_connected is False
    assert manager.expected_incoming_sequence == 3


def test_sequence_session_sync_is_idempotent_for_transport_reconnects():
    manager = _manager(FakeWebSocket([]), session_id="sess-001", outgoing=8, incoming=11)

    manager._sync_sequence_session("sess-001")

    assert manager.next_outgoing_sequence == 8
    assert manager.expected_incoming_sequence == 11
    assert manager._sequence_session_id == "sess-001"


def test_sequence_session_sync_resets_only_when_logical_session_changes():
    manager = _manager(FakeWebSocket([]), session_id="sess-old", outgoing=8, incoming=11)

    manager._sync_sequence_session("sess-new")

    assert manager.next_outgoing_sequence == 0
    assert manager.expected_incoming_sequence == 0
    assert manager._sequence_session_id == "sess-new"
    assert manager._sequence_state_initialized is True


@pytest.mark.asyncio
async def test_handshake_fails_on_unexpected_frame_type():
    frames = _handshake_frames("sess-unexpected")
    frames[1] = _frame(
        FrameType.HEARTBEAT_ACK,
        "sess-unexpected",
        1,
        {"timestamp": 100.0},
    )
    ws = FakeWebSocket(frames)
    manager = _manager(ws)

    result = await manager._perform_handshake(_models())

    assert result is False
    assert manager.is_connected is False
    assert manager.session_id == "sess-unexpected"
    assert manager.expected_incoming_sequence == 1
    assert ws.closed is True


@pytest.mark.asyncio
async def test_handshake_fails_on_malformed_payload():
    frames = _handshake_frames("sess-malformed")
    frames[1] = ProtocolEnvelope(
        type=FrameType.REGISTER_ACK,
        session_id="sess-malformed",
        sequence=1,
        payload={
            "registered_models": ["llama3"],
            "unexpected": True,
        },
    ).to_json()
    ws = FakeWebSocket(frames)
    manager = _manager(ws)

    with pytest.raises(ValidationError):
        ProtocolEnvelope.model_validate_json(frames[1])

    result = await manager._perform_handshake(_models())

    assert result is False
    assert manager.is_connected is False
    assert manager.session_id == "sess-malformed"
    assert manager.expected_incoming_sequence == 1
    assert ws.closed is True


@pytest.mark.asyncio
async def test_handshake_fails_on_malformed_json():
    frames = _handshake_frames("sess-json")
    frames[1] = "{not-valid-json"
    ws = FakeWebSocket(frames)
    manager = _manager(ws)

    result = await manager._perform_handshake(_models())

    assert result is False
    assert manager.is_connected is False
    assert manager.session_id == "sess-json"
    assert manager.expected_incoming_sequence == 1
    assert ws.closed is True
