"""
Connection Supervisor for Zephyr SDK.

Handles outbound WebSocket (WSS) communication with Zephyr Cloud, canonical ProtocolEnvelope
framing (version 1.0), bootstrap authentication, hardware telemetry, heartbeat keepalives,
directional sequence tracking and validation, and automatic reconnection.
"""

import asyncio
import json
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional
import httpx

try:
    import websockets
    try:
        from websockets.asyncio.client import ClientConnection as WebSocketClientProtocol
    except ImportError:
        from websockets.client import WebSocketClientProtocol  # type: ignore
except ImportError:
    websockets = None  # type: ignore
    WebSocketClientProtocol = Any  # type: ignore

from viento.backends.base import InferenceBackend
from viento.backends.ollama import OllamaAdapter
from viento.config.loader import ConfigManager, RuntimeState, ZephyrConfig
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
    ModelInfo,
    ProtocolEnvelope,
    RegisterPayload,
    TokenChunkPayload,
)
from viento.telemetry.collector import TelemetryCollector

logger = logging.getLogger("viento.connection")


class ConnectionManager:
    """
    Supervisor managing persistent WebSocket connection with Zephyr Cloud gateway.
    """

    def __init__(
        self,
        config: Optional[ZephyrConfig] = None,
        config_manager: Optional[ConfigManager] = None,
        backend: Optional[InferenceBackend] = None,
    ):
        self.config_manager = config_manager or ConfigManager()
        self.config = config or self.config_manager.load_config()
        self.backend: InferenceBackend = backend or OllamaAdapter(base_url=self.config.ollama_url)
        self.telemetry = TelemetryCollector()

        self.ws: Optional[WebSocketClientProtocol] = None
        self.is_connected: bool = False
        self.is_running: bool = False
        self.session_id: Optional[str] = None
        self.active_api_key: Optional[str] = None
        self.key_expires_at: Optional[float] = None

        self.next_outgoing_sequence: int = 0
        self.expected_incoming_sequence: int = 0

        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Event Callbacks
        self.on_handshake_callback: Optional[Callable[[str, str, float], None]] = None
        self.on_job_received_callback: Optional[Callable[[ProtocolEnvelope], None]] = None
        self.on_embedding_received_callback: Optional[Callable[[ProtocolEnvelope], None]] = None
        self.on_job_cancel_callback: Optional[Callable[[str], None]] = None
        self.on_disconnect_callback: Optional[Callable[[], None]] = None

    def _get_next_sequence(self) -> int:
        seq = self.next_outgoing_sequence
        self.next_outgoing_sequence += 1
        return seq

    async def send_envelope(self, envelope: ProtocolEnvelope) -> None:
        if self.ws and self.is_connected:
            envelope.sequence = self._get_next_sequence()
            envelope.session_id = self.session_id
            await self.ws.send(envelope.to_json())

    async def start(self) -> None:
        self.is_running = True
        self._shutdown_event.clear()

        models = await self.discover_local_models()
        self.config_manager.update_runtime_state(
            status="booting",
            uptime_start=time.time(),
            registered_models=[m.name for m in models],
        )

        backoff = 1.0
        max_backoff = 30.0

        while self.is_running and not self._shutdown_event.is_set():
            try:
                logger.info(f"Connecting to Zephyr Cloud at {self.config.server_url}...")
                if websockets is None:
                    raise RuntimeError("websockets library is required.")

                async with websockets.connect(
                    self.config.server_url,
                    max_size=5_242_880,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    self.ws = ws
                    self.is_connected = True
                    self.next_outgoing_sequence = 0
                    self.expected_incoming_sequence = 0
                    backoff = 1.0

                    handshake_success = await self._perform_handshake(models)
                    if not handshake_success:
                        logger.error("Handshake failed. Reconnecting...")
                        await asyncio.sleep(2.0)
                        continue

                    logger.info(f"Handshake successful. Session ID: {self.session_id}")

                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    await self._receive_loop()

            except asyncio.CancelledError:
                logger.info("Connection manager task cancelled.")
                break
            except Exception as e:
                self.is_connected = False
                logger.warning(f"WebSocket connection error: {e}")
                self.config_manager.update_runtime_state(status="reconnecting")

            if self.is_running and not self._shutdown_event.is_set():
                jitter = random.uniform(-0.2, 0.2) * backoff
                sleep_time = min(max_backoff, backoff + jitter)
                logger.info(f"Retrying connection in {sleep_time:.2f}s...")
                await asyncio.sleep(sleep_time)
                backoff = min(max_backoff, backoff * 2.0)

        await self._cleanup()

    async def discover_local_models(self) -> List[ModelInfo]:
        try:
            raw_models = await asyncio.to_thread(self.backend.list_models)
            model_infos: List[ModelInfo] = []
            for m in raw_models:
                if isinstance(m, dict):
                    m_name = m.get("name") or m.get("id") or m.get("model", "unknown")
                    model_infos.append(
                        ModelInfo(
                            id=m_name,
                            name=m_name,
                            status="ready",
                            backend=self.backend.name(),
                            context_length=m.get("context_length", 8192),
                            quantization=m.get("details", {}).get("quantization_level", "unknown"),
                            capabilities=self.backend.capabilities(),
                            max_concurrency=self.config.max_concurrency,
                        )
                    )
                elif isinstance(m, str):
                    model_infos.append(
                        ModelInfo(
                            id=m,
                            name=m,
                            status="ready",
                            backend=self.backend.name(),
                            capabilities=self.backend.capabilities(),
                            max_concurrency=self.config.max_concurrency,
                        )
                    )
            logger.info(f"Discovered models via backend '{self.backend.name()}': {[m.name for m in model_infos]}")
            return model_infos
        except Exception as e:
            logger.warning(f"Could not discover models from backend '{self.backend.name()}': {e}")
            return []

    def _validate_incoming_sequence(self, envelope: ProtocolEnvelope) -> bool:
        """Validate incoming sequence number strictly per session direction."""
        incoming_seq = envelope.sequence
        expected = self.expected_incoming_sequence

        if incoming_seq == expected:
            self.expected_incoming_sequence += 1
            return True
        elif incoming_seq < expected:
            logger.warning("SDK received duplicate frame seq %d (expected %d). Ignoring.", incoming_seq, expected)
            return False
        else:
            logger.error("SDK sequence gap: received seq %d (expected %d). Disconnecting.", incoming_seq, expected)
            self.is_connected = False
            return False

    async def _perform_handshake(self, models: List[ModelInfo]) -> bool:
        try:
            # 1. Send HELLO
            hello_payload = HelloPayload(
                runtime_id=self.config.node_name,
                version="1.0.0",
                auth_key=self.config.bootstrap_key or None,
                session_id=self.session_id,  # Reconnect recovery hint
            )
            hello_envelope = ProtocolEnvelope(
                type=FrameType.HELLO,
                payload=hello_payload.model_dump(),
            )
            await self.send_envelope(hello_envelope)

            # Await WELCOME
            raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            welcome_envelope = ProtocolEnvelope.from_json(raw_msg)
            if welcome_envelope.type != FrameType.WELCOME:
                logger.error(f"Expected WELCOME, got: {welcome_envelope.type}")
                return False

            if not self._validate_incoming_sequence(welcome_envelope):
                return False

            p_welcome = welcome_envelope.payload
            self.session_id = p_welcome.get("session_id", f"sess_{int(time.time())}")

            # 2. Collect Real Hardware Snapshot
            hw_snap = self.telemetry.get_hardware_snapshot()
            
            # Extract GPU stats if present
            gpu_name = "CPU"
            vram_total_mb = 0
            vram_used_mb = 0
            device_count = 0
            
            if hw_snap.gpus:
                first_gpu = hw_snap.gpus[0]
                gpu_name = first_gpu.name
                vram_total_mb = int(first_gpu.memory_total_mb)
                vram_used_mb = int(first_gpu.memory_used_mb)
                device_count = len(hw_snap.gpus)
            
            hardware = HardwareSpecs(
                cpu_count=hw_snap.cpu_count_logical,
                ram_total_mb=int(hw_snap.memory_total_bytes / (1024**2)),
                ram_used_mb=int(hw_snap.memory_used_bytes / (1024**2)),
                gpu_name=gpu_name,
                vram_total_mb=vram_total_mb,
                vram_used_mb=vram_used_mb,
                device_count=device_count,
                max_sequence_length=4096,
            )

            # Send REGISTER
            reg_payload = RegisterPayload(
                runtime_name=self.config.node_name,
                hardware=hardware,
                models=models,
                supported_models=[m.name for m in models],
            )
            reg_envelope = ProtocolEnvelope(
                type=FrameType.REGISTER,
                session_id=self.session_id,
                payload=reg_payload.model_dump(),
            )
            await self.send_envelope(reg_envelope)

            # Await REGISTER_ACK
            raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            reg_ack_envelope = ProtocolEnvelope.from_json(raw_msg)
            if reg_ack_envelope.type != FrameType.REGISTER_ACK:
                logger.error(f"Expected REGISTER_ACK, got: {reg_ack_envelope.type}")
                return False

            if not self._validate_incoming_sequence(reg_ack_envelope):
                return False

            # Await SESSION_READY
            raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            session_ready_envelope = ProtocolEnvelope.from_json(raw_msg)
            if session_ready_envelope.type != FrameType.SESSION_READY:
                logger.error(f"Expected SESSION_READY, got: {session_ready_envelope.type}")
                return False

            if not self._validate_incoming_sequence(session_ready_envelope):
                return False

            p_ready = session_ready_envelope.payload
            self.active_api_key = p_ready.get("api_key")
            ttl = float(p_ready.get("ttl_seconds", 3600))
            self.key_expires_at = float(p_ready.get("expires_at", time.time() + ttl))

            self.config_manager.update_runtime_state(
                session_id=self.session_id,
                active_api_key=self.active_api_key,
                key_expires_at=self.key_expires_at,
                registered_models=[m.name for m in models],
                status="running",
                last_heartbeat=time.time(),
            )

            if self.on_handshake_callback:
                self.on_handshake_callback(self.active_api_key, self.session_id, ttl)

            return True

        except Exception as e:
            logger.error(f"Handshake error: {e}")
            return False

    async def _heartbeat_loop(self) -> None:
        while self.is_connected and self.is_running:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
                if self.ws and self.is_connected:
                    snap = self.telemetry.collect_snapshot()
                    hb_payload = HeartbeatPayload(
                        active_jobs=snap.active_jobs_count,
                        metrics=snap.to_dict(),
                    )
                    envelope = ProtocolEnvelope(
                        type=FrameType.HEARTBEAT,
                        session_id=self.session_id,
                        payload=hb_payload.model_dump(),
                    )
                    await self.send_envelope(envelope)
                    self.config_manager.update_runtime_state(last_heartbeat=time.time())
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat ping failed: {e}")

    async def _receive_loop(self) -> None:
        while self.is_connected and self.ws:
            try:
                raw_msg = await self.ws.recv()
                envelope = ProtocolEnvelope.from_json(raw_msg)

                if not self._validate_incoming_sequence(envelope):
                    continue

                msg_type = envelope.type

                if msg_type == FrameType.JOB_REQUEST:
                    if self.on_job_received_callback:
                        self.on_job_received_callback(envelope)
                elif msg_type == FrameType.EMBEDDING_REQUEST:
                    if self.on_embedding_received_callback:
                        self.on_embedding_received_callback(envelope)
                elif msg_type == FrameType.CANCEL_JOB:
                    job_id = envelope.job_id
                    if job_id:
                        if self.on_job_cancel_callback:
                            if asyncio.iscoroutinefunction(self.on_job_cancel_callback):
                                await self.on_job_cancel_callback(job_id)
                            else:
                                self.on_job_cancel_callback(job_id)
                        # Transmit CANCEL_ACK ONLY AFTER cancellation processing is complete!
                        await self.send_cancel_ack(job_id, envelope.request_id)
                elif msg_type in (FrameType.HEARTBEAT_ACK, FrameType.REGISTER_ACK, FrameType.CANCEL_ACK, FrameType.JOB_ACK):
                    pass
                elif msg_type in (FrameType.DISCONNECT,):
                    logger.info("Received disconnect request from cloud gateway.")
                    await self.stop()
                    break

            except asyncio.CancelledError:
                break
            except websockets.exceptions.ConnectionClosed:
                logger.info("Server closed connection.")
                self.is_connected = False
                break
            except Exception as e:
                logger.error(f"Error processing frame: {e}")

    async def send_job_ack(self, job_id: str, request_id: Optional[str] = None, queue_position: int = 0) -> None:
        payload = JobAckPayload(status="accepted", queue_position=queue_position)
        envelope = ProtocolEnvelope(
            type=FrameType.JOB_ACK,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def send_cancel_ack(self, job_id: str, request_id: Optional[str] = None) -> None:
        payload = CancelAckPayload(status="cancelled")
        envelope = ProtocolEnvelope(
            type=FrameType.CANCEL_ACK,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def send_job_chunk(
        self, job_id: str, chunk: str, request_id: Optional[str] = None, index: int = 0, is_final: bool = False
    ) -> None:
        payload = TokenChunkPayload(
            delta=chunk,
            index=index,
            finish_reason="stop" if is_final else None,
        )
        envelope = ProtocolEnvelope(
            type=FrameType.TOKEN_CHUNK,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def send_job_complete(
        self, job_id: str, result: Dict[str, Any], request_id: Optional[str] = None
    ) -> None:
        payload = JobCompletePayload(
            finish_reason=result.get("finish_reason", "stop") or "stop",
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            is_estimated=result.get("is_estimated", False),
        )
        envelope = ProtocolEnvelope(
            type=FrameType.JOB_COMPLETE,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def send_embedding_response(
        self,
        job_id: str,
        model: str,
        embeddings: List[List[float]],
        request_id: Optional[str] = None,
        prompt_tokens: int = 0,
        total_tokens: int = 0,
        is_estimated: bool = False,
    ) -> None:
        payload = EmbeddingResponsePayload(
            model=model,
            embeddings=embeddings,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            is_estimated=is_estimated,
        )
        envelope = ProtocolEnvelope(
            type=FrameType.EMBEDDING_RESPONSE,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def send_job_error(
        self, job_id: str, error: str, request_id: Optional[str] = None
    ) -> None:
        payload = JobErrorPayload(
            error_message=error,
            error_code="runtime_error",
        )
        envelope = ProtocolEnvelope(
            type=FrameType.JOB_ERROR,
            request_id=request_id,
            job_id=job_id,
            payload=payload.model_dump(),
        )
        await self.send_envelope(envelope)

    async def stop(self) -> None:
        logger.info("Stopping ConnectionManager...")
        self.is_running = False
        self._shutdown_event.set()

        if self.ws and self.is_connected:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.is_connected = False

        if self.on_disconnect_callback:
            self.on_disconnect_callback()

        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self.config_manager.update_runtime_state(status="stopped")
