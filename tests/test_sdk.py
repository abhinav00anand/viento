"""Unit tests for SDK CLI, config loader, connection manager, and scheduler."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from viento.backends.base import ExecutionHandle, GenerationResult
from viento.client.client import AsyncVientoClient, VientoClient
from viento.config.loader import ConfigManager, RuntimeState, ZephyrConfig
from viento.connection.manager import ConnectionManager
from viento.scheduler.scheduler import JobScheduler, JobStatus


def test_config_defaults_and_serialization(tmp_path):
    cm = ConfigManager(base_dir=tmp_path)
    cfg = cm.load_config()

    assert cfg.server_url == "wss://viento.onrender.com/ws/runtime"
    assert cfg.model_backend == "ollama"

    # Secret non-persistence assertion
    d = cfg.to_dict()
    assert "bootstrap_key" not in d


def test_runtime_state_security_stripping(tmp_path):
    cm = ConfigManager(base_dir=tmp_path)
    state = RuntimeState(session_id="sess_123", active_key="zph_tmp_secret_123")
    cm.save_runtime_state(state)

    loaded = cm.load_runtime_state()
    assert loaded.session_id == "sess_123"
    assert loaded.active_key is None  # Active key stripped before disk save


def test_connection_manager_init():
    cfg = ZephyrConfig()
    cm = ConnectionManager(config=cfg)
    assert cm.is_connected is False
    assert cm.session_id is None


@pytest.mark.asyncio
async def test_scheduler_queue_and_cancellation():
    backend = MagicMock()
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_error = AsyncMock()

    scheduler = JobScheduler(backend=backend, connection_manager=conn, max_queue_depth=2)

    env = MagicMock()
    env.job_id = "job_1"
    env.request_id = "req_1"
    env.type = "job_request"
    env.session_id = "sess_1"
    env.payload = {"model": "llama3:latest", "messages": []}

    res = await scheduler.submit_job(env)
    assert res is True
    assert conn.send_job_ack.called

    scheduler.cancel_job("job_1")
    assert backend.cancel.called


@pytest.mark.asyncio
async def test_queued_job_cancellation_skips_backend_execution():
    backend = MagicMock()
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_complete = AsyncMock()

    scheduler = JobScheduler(backend=backend, connection_manager=conn)

    env = MagicMock()
    env.job_id = "job_queued_test"
    env.request_id = "req_q1"
    env.type = "job_request"
    env.session_id = "sess_1"
    env.payload = {"model": "llama3:latest", "messages": []}

    # Submit job to queue BEFORE starting worker loop
    await scheduler.submit_job(env)
    assert scheduler.queue.qsize() == 1

    # Cancel job while in queue
    scheduler.cancel_job("job_queued_test")
    assert scheduler._jobs["job_queued_test"].status == JobStatus.CANCELLED

    # Now start worker loop and let it process the queued item
    await scheduler.start()
    await asyncio.sleep(0.1)
    await scheduler.stop()

    # Verify backend.generate was NEVER called for the cancelled queued job
    assert not backend.generate.called
    assert not conn.send_job_complete.called


@pytest.mark.asyncio
async def test_running_job_cancellation_aborts_handle_and_suppresses_complete():
    backend = MagicMock()
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_chunk = AsyncMock()
    conn.send_job_complete = AsyncMock()

    handle_mock = MagicMock(spec=ExecutionHandle)
    job_started_ev = threading.Event()
    job_can_finish_ev = threading.Event()

    def slow_generate(job_id, model, messages, temperature, max_tokens, callback, stop, handle_callback):
        if handle_callback:
            handle_callback(handle_mock)
        job_started_ev.set()
        job_can_finish_ev.wait(timeout=2.0)
        return GenerationResult(full_text="hello", prompt_tokens=2, completion_tokens=1, total_tokens=3), handle_mock

    backend.generate.side_effect = slow_generate

    scheduler = JobScheduler(backend=backend, connection_manager=conn)
    await scheduler.start()

    env = MagicMock()
    env.job_id = "job_running_test"
    env.request_id = "req_r1"
    env.type = "job_request"
    env.session_id = "sess_1"
    env.payload = {"model": "llama3:latest", "messages": []}

    await scheduler.submit_job(env)

    # Wait for generator thread to start and register handle
    await asyncio.to_thread(job_started_ev.wait, 2.0)

    # Cancel while job is running
    scheduler.cancel_job("job_running_test")
    job_can_finish_ev.set()

    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert handle_mock.cancel.called
    assert not conn.send_job_complete.called


@pytest.mark.asyncio
async def test_scheduler_stop_purges_queue_and_drains_tasks():
    backend = MagicMock()
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()

    scheduler = JobScheduler(backend=backend, connection_manager=conn)

    for i in range(5):
        env = MagicMock()
        env.job_id = f"job_stop_{i}"
        env.request_id = f"req_{i}"
        env.type = "job_request"
        env.session_id = "sess_1"
        env.payload = {"model": "llama3:latest", "messages": []}
        await scheduler.submit_job(env)

    assert scheduler.queue.qsize() == 5

    # Stop scheduler — must purge queue with task_done() and drain active tasks without hanging
    await scheduler.stop()

    assert scheduler.queue.qsize() == 0


def test_client_headers_and_init():
    client = VientoClient(base_url="https://zephyr-i2ho.onrender.com", api_key="zph_tmp_123")
    assert client.api_key == "zph_tmp_123"
    headers = client._headers()
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer zph_tmp_123"


def test_async_client_headers_and_init():
    async_client = AsyncVientoClient(base_url="https://zephyr-i2ho.onrender.com", api_key="zph_tmp_123")
    assert async_client.api_key == "zph_tmp_123"
    headers = async_client._headers()
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer zph_tmp_123"
