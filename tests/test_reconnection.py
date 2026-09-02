"""Regression tests for reconnect and logical-session sequence semantics."""

import asyncio

import pytest
import websockets

import viento.connection.manager as connection_manager_module
from viento.config.loader import VientoConfig
from viento.connection.manager import ConnectionManager
from viento.protocol.envelope import FrameType, ModelInfo, ProtocolEnvelope


class FakeConfigManager:
    def update_runtime_state(self, **kwargs):
        pass


class FakeBackend:
    def name(self):
        return "test"

    def capabilities(self):
        return ["chat", "streaming"]

    def list_models(self):
        return []


class FakeHardwareSnapshot:
    cpu_count_logical = 8
    memory_total_bytes = 16 * 1024**3
    memory_used_bytes = 4 * 1024**3
    gpus = []


class FakeTelemetry:
    def get_hardware_snapshot(self):
        return FakeHardwareSnapshot()


class FakeWebSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    async def recv(self):
        await asyncio.sleep(0)
        if not self.frames:
            raise websockets.exceptions.ConnectionClosedOK(None, None)
        return self.frames.pop(0)

    async def send(self, raw):
        self.sent.append(ProtocolEnvelope.model_validate_json(raw))

    async def close(self):
        self.closed = True


class FakeWebSocketContext:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        await self.websocket.close()
        return False


def _config():
    return VientoConfig(
        node_name="test-node",
        bootstrap_key="bootstrap-secret",
        max_concurrency=2,
        server_url="wss://example.invalid/ws",
        ollama_url="http://localhost:11434",
        heartbeat_interval=15.0,
    )


def _manager(ws, *, session_id=None, outgoing=0, incoming=0):
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


def _handshake_frames(session_id, *, start_sequence=0, api_key="vnt_tmp_test"):
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
async def test_new_session_starts_sequences_at_zero():
    ws = FakeWebSocket(_handshake_frames("sess-new"))
    manager = _manager(ws)

    assert await manager._perform_handshake(_models()) is True
    assert manager.session_id == "sess-new"
    assert manager._sequence_session_id == "sess-new"
    assert manager.next_outgoing_sequence == 1
    assert manager.expected_incoming_sequence == 3
    assert [frame.sequence for frame in ws.sent] == [0, 0]
    assert ws.sent[0].session_id is None
    assert ws.sent[1].session_id == "sess-new"


@pytest.mark.asyncio
async def test_resumed_session_preserves_sequence_state():
    ws = FakeWebSocket(_handshake_frames("sess-existing", start_sequence=7))
    manager = _manager(ws, session_id="sess-existing", outgoing=5, incoming=7)

    assert await manager._perform_handshake(_models()) is True
    assert manager.next_outgoing_sequence == 7
    assert manager.expected_incoming_sequence == 10
    assert [frame.sequence for frame in ws.sent] == [5, 6]
    assert [frame.session_id for frame in ws.sent] == ["sess-existing", "sess-existing"]


@pytest.mark.asyncio
async def test_changed_session_starts_new_sequence_epoch():
    ws = FakeWebSocket(_handshake_frames("sess-new"))
    manager = _manager(ws, session_id="sess-old", outgoing=42, incoming=18)

    assert await manager._perform_handshake(_models()) is True
    assert manager.session_id == "sess-new"
    assert manager._sequence_session_id == "sess-new"
    assert manager.next_outgoing_sequence == 1
    assert manager.expected_incoming_sequence == 3
    assert [frame.sequence for frame in ws.sent] == [42, 0]


@pytest.mark.asyncio
async def test_start_reconnects_same_session_and_closes_transports(monkeypatch):
    first_ws = FakeWebSocket(_handshake_frames("sess-initial"))
    second_ws = FakeWebSocket(_handshake_frames("sess-initial", start_sequence=3))
    sockets = [first_ws, second_ws]

    def fake_connect(*args, **kwargs):
        return FakeWebSocketContext(sockets.pop(0))

    monkeypatch.setattr(connection_manager_module.websockets, "connect", fake_connect)

    manager = ConnectionManager(
        config=_config(),
        config_manager=FakeConfigManager(),
        backend=FakeBackend(),
    )
    manager.telemetry = FakeTelemetry()

    handshakes = []

    def on_handshake(api_key, session_id, ttl):
        handshakes.append((api_key, session_id, ttl))
        if len(handshakes) == 2:
            manager.is_running = False

    manager.on_handshake_callback = on_handshake

    await manager.start()

    assert first_ws.closed is True
    assert second_ws.closed is True
    assert [frame.sequence for frame in first_ws.sent] == [0, 0]
    assert [frame.sequence for frame in second_ws.sent] == [1, 2]
    assert manager.session_id == "sess-initial"
    assert manager.next_outgoing_sequence == 3
    assert manager.expected_incoming_sequence == 6


@pytest.mark.asyncio
async def test_start_reconnects_after_malformed_handshake(monkeypatch):
    malformed = _frame(
        FrameType.REGISTER_ACK,
        "sess-failed",
        1,
        {"registered_models": ["llama3"], "unexpected": True},
    )
    failed_ws = FakeWebSocket(
        [
            _frame(
                FrameType.WELCOME,
                "sess-failed",
                0,
                {
                    "session_id": "sess-failed",
                    "assigned_at": 100.0,
                    "heartbeat_interval": 15.0,
                },
            ),
            malformed,
        ]
    )
    recovered_ws = FakeWebSocket(_handshake_frames("sess-recovered"))
    sockets = [failed_ws, recovered_ws]
    attempts = []

    def fake_connect(*args, **kwargs):
        attempts.append(args[0])
        return FakeWebSocketContext(sockets.pop(0))

    monkeypatch.setattr(connection_manager_module.websockets, "connect", fake_connect)

    manager = ConnectionManager(
        config=_config(),
        config_manager=FakeConfigManager(),
        backend=FakeBackend(),
    )

    def on_handshake(api_key, session_id, ttl):
        manager.is_running = False

    manager.on_handshake_callback = on_handshake

    await manager.start()

    assert len(attempts) == 2
    assert failed_ws.closed is True
    assert recovered_ws.closed is True
    assert manager.session_id == "sess-recovered"


def test_invalid_welcome_sequence_does_not_mutate_state():
    manager = _manager(FakeWebSocket([]), session_id="sess-existing", outgoing=12, incoming=9)
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
    assert manager.next_outgoing_sequence == 12
    assert manager.expected_incoming_sequence == 9


def test_duplicate_frame_is_rejected_without_advancing_sequence():
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


def test_sequence_gap_disconnects_without_advancing_sequence():
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


def test_foreign_session_frame_disconnects_without_advancing_sequence():
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


def test_sequence_sync_preserves_same_session_and_resets_changes():
    manager = _manager(FakeWebSocket([]), session_id="sess-old", outgoing=8, incoming=11)

    manager._sync_sequence_session("sess-old")
    assert manager.next_outgoing_sequence == 8
    assert manager.expected_incoming_sequence == 11

    manager._sync_sequence_session("sess-new")
    assert manager.next_outgoing_sequence == 0
    assert manager.expected_incoming_sequence == 0
    assert manager._sequence_session_id == "sess-new"
