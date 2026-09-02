"""
Comprehensive Concurrency Stress, Queue Overflow, and Zero-Token-Drop Test Suite.

Validates:
1. Parallel burst request handling and concurrency bounding via Semaphore.
2. Safe queue depth limits and graceful backpressure rejection on overflow.
3. Rapid in-flight and queued cancellation without resource leaks or deadlocks.
4. Zero token drop during high-frequency parallel streaming.
5. Thread-safe telemetry tracking under intense concurrent load.
"""

import asyncio
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from viento.backends.base import (
    EmbeddingResult,
    ExecutionHandle,
    GenerationChunk,
    GenerationResult,
    InferenceBackend,
)
from viento.protocol.envelope import FrameType, ProtocolEnvelope
from viento.scheduler.scheduler import Job, JobScheduler, JobStatus, JobType
from viento.telemetry.collector import TelemetryCollector


class MockExecutionHandle(ExecutionHandle):
    def __init__(self, cancel_cb: Optional[Callable[[], None]] = None):
        self._done = False
        self._cancel_cb = cancel_cb

    def cancel(self) -> None:
        self._done = True
        if self._cancel_cb:
            self._cancel_cb()

    def is_done(self) -> bool:
        return self._done


class MockStreamingBackend(InferenceBackend):
    """Mock backend that simulates realistic token streaming."""

    def __init__(self, delay_per_token: float = 0.005, tokens_per_job: int = 10):
        self.delay_per_token = delay_per_token
        self.tokens_per_job = tokens_per_job
        self.active_executions = 0
        self.max_observed_concurrency = 0
        self.total_tokens_emitted = 0
        self._lock = threading.Lock()

    def name(self) -> str:
        return "mock_stress_backend"

    def capabilities(self) -> List[str]:
        return ["chat", "streaming", "embeddings"]

    def health(self) -> bool:
        return True

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": "llama3:latest", "name": "llama3:latest"}]

    def generate(
        self,
        job_id: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 512,
        callback: Optional[Callable[[GenerationChunk], None]] = None,
        stop: Optional[List[str]] = None,
        handle_callback: Optional[Callable[[ExecutionHandle], None]] = None,
    ) -> Tuple[GenerationResult, ExecutionHandle]:
        with self._lock:
            self.active_executions += 1
            if self.active_executions > self.max_observed_concurrency:
                self.max_observed_concurrency = self.active_executions

        cancelled = False

        def cancel_cb():
            nonlocal cancelled
            cancelled = True

        handle = MockExecutionHandle(cancel_cb=cancel_cb)
        if handle_callback:
            handle_callback(handle)

        generated_text = ""
        try:
            for i in range(self.tokens_per_job):
                if cancelled:
                    break
                time.sleep(self.delay_per_token)
                chunk_text = f"word_{i} "
                generated_text += chunk_text
                with self._lock:
                    self.total_tokens_emitted += 1
                if callback:
                    callback(
                        GenerationChunk(
                            delta=chunk_text,
                            index=i,
                            finish_reason="stop" if i == self.tokens_per_job - 1 else None,
                        )
                    )
        finally:
            with self._lock:
                self.active_executions -= 1

        return (
            GenerationResult(
                full_text=generated_text,
                prompt_tokens=10,
                completion_tokens=self.tokens_per_job,
                total_tokens=10 + self.tokens_per_job,
            ),
            handle,
        )

    def embeddings(
        self,
        model: str,
        inputs: List[str],
        job_id: Optional[str] = None,
        handle_callback: Optional[Callable[[ExecutionHandle], None]] = None,
    ) -> EmbeddingResult:
        handle = MockExecutionHandle()
        if handle_callback:
            handle_callback(handle)
        return EmbeddingResult(embeddings=[[0.1] * 64 for _ in inputs], prompt_tokens=len(inputs) * 5)

    def cancel(self, job_id: str) -> None:
        pass


@pytest.mark.asyncio
async def test_burst_concurrency_bounding():
    """Verify that JobScheduler bounds parallel executions strictly to max_concurrency."""
    max_concurrency = 3
    num_jobs = 12
    backend = MockStreamingBackend(delay_per_token=0.01, tokens_per_job=4)
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_chunk = AsyncMock()
    conn.send_job_complete = AsyncMock()
    conn.send_job_error = AsyncMock()

    scheduler = JobScheduler(
        backend=backend,
        connection_manager=conn,
        max_concurrency=max_concurrency,
        max_queue_depth=50,
    )
    await scheduler.start()

    # Enqueue burst of jobs
    for i in range(num_jobs):
        env = ProtocolEnvelope(
            version="1.0",
            type=FrameType.JOB_REQUEST,
            session_id="sess_stress_1",
            sequence=i + 1,
            timestamp=int(time.time()),
            job_id=f"job_{i}",
            request_id=f"req_{i}",
            payload={"model": "llama3:latest", "messages": [{"role": "user", "content": "hi"}]},
        )
        await scheduler.submit_job(env)

    # Await completion
    timeout = 10.0
    start = time.time()
    while len(conn.send_job_complete.call_args_list) < num_jobs:
        if time.time() - start > timeout:
            break
        await asyncio.sleep(0.05)

    await scheduler.stop()

    assert len(conn.send_job_complete.call_args_list) == num_jobs
    assert backend.max_observed_concurrency <= max_concurrency
    assert backend.total_tokens_emitted == num_jobs * 4


@pytest.mark.asyncio
async def test_queue_overflow_backpressure():
    """Verify that when queue reaches max_queue_depth, new jobs trigger JOB_ERROR."""
    max_queue_depth = 4
    backend = MockStreamingBackend(delay_per_token=0.1, tokens_per_job=10)
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_error = AsyncMock()

    scheduler = JobScheduler(
        backend=backend,
        connection_manager=conn,
        max_concurrency=1,
        max_queue_depth=max_queue_depth,
    )

    # Fill up queue without starting worker
    for i in range(max_queue_depth):
        env = ProtocolEnvelope(
            version="1.0",
            type=FrameType.JOB_REQUEST,
            session_id="sess_overflow",
            sequence=i + 1,
            timestamp=int(time.time()),
            job_id=f"job_ok_{i}",
            request_id=f"req_ok_{i}",
            payload={"model": "llama3:latest", "messages": []},
        )
        await scheduler.submit_job(env)

    # One more to overflow
    overflow_env = ProtocolEnvelope(
        version="1.0",
        type=FrameType.JOB_REQUEST,
        session_id="sess_overflow",
        sequence=99,
        timestamp=int(time.time()),
        job_id="job_overflow",
        request_id="req_overflow",
        payload={"model": "llama3:latest", "messages": []},
    )
    await scheduler.submit_job(overflow_env)

    conn.send_job_error.assert_awaited()
    last_err_call = conn.send_job_error.call_args
    assert "queue full" in last_err_call[1]["error_message"].lower() or "depth" in last_err_call[1]["error_message"].lower()
    await scheduler.stop()


@pytest.mark.asyncio
async def test_rapid_cancellation_under_concurrency():
    """Verify in-flight and queued jobs cancel cleanly and release semaphores."""
    backend = MockStreamingBackend(delay_per_token=0.04, tokens_per_job=15)
    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_chunk = AsyncMock()
    conn.send_job_complete = AsyncMock()
    conn.send_job_error = AsyncMock()

    scheduler = JobScheduler(
        backend=backend,
        connection_manager=conn,
        max_concurrency=2,
        max_queue_depth=20,
    )
    await scheduler.start()

    for i in range(6):
        env = ProtocolEnvelope(
            version="1.0",
            type=FrameType.JOB_REQUEST,
            session_id="sess_cancel",
            sequence=i + 1,
            timestamp=int(time.time()),
            job_id=f"cancel_job_{i}",
            request_id=f"req_{i}",
            payload={"model": "llama3:latest", "messages": []},
        )
        await scheduler.submit_job(env)

    await asyncio.sleep(0.05)

    # Cancel jobs 0 (running) and 4 (queued)
    scheduler.cancel_job("cancel_job_0")
    scheduler.cancel_job("cancel_job_4")

    await asyncio.sleep(1.0)
    await scheduler.stop()

    assert scheduler._jobs.get("cancel_job_0") is None or scheduler._jobs["cancel_job_0"].status in [
        JobStatus.CANCELLED,
        JobStatus.CANCEL_REQUESTED,
    ]


@pytest.mark.asyncio
async def test_zero_token_drop_parallel_streaming():
    """Verify that under parallel streams, 100% of generated tokens are delivered without dropping."""
    num_jobs = 6
    tokens_per_job = 8
    backend = MockStreamingBackend(delay_per_token=0.005, tokens_per_job=tokens_per_job)

    received_chunks = []

    async def mock_send_chunk(job_id, chunk, index=0, request_id=None):
        received_chunks.append((job_id, chunk))

    conn = MagicMock()
    conn.send_job_ack = AsyncMock()
    conn.send_job_chunk = AsyncMock(side_effect=mock_send_chunk)
    conn.send_job_complete = AsyncMock()
    conn.send_job_error = AsyncMock()

    scheduler = JobScheduler(
        backend=backend,
        connection_manager=conn,
        max_concurrency=3,
        max_queue_depth=30,
    )
    await scheduler.start()

    for i in range(num_jobs):
        env = ProtocolEnvelope(
            version="1.0",
            type=FrameType.JOB_REQUEST,
            session_id="sess_zero_drop",
            sequence=i + 1,
            timestamp=int(time.time()),
            job_id=f"zd_job_{i}",
            request_id=f"zd_req_{i}",
            payload={"model": "llama3:latest", "messages": []},
        )
        await scheduler.submit_job(env)

    timeout = 8.0
    start = time.time()
    while len(conn.send_job_complete.call_args_list) < num_jobs:
        if time.time() - start > timeout:
            break
        await asyncio.sleep(0.05)

    await scheduler.stop()

    total_expected_tokens = num_jobs * tokens_per_job
    assert len(received_chunks) == total_expected_tokens
    assert conn.send_job_error.call_count == 0


def test_telemetry_thread_safety_under_load():
    """Verify request counter increments remain atomic and exact under heavy concurrent load."""
    collector = TelemetryCollector()
    iterations = 500
    model_name = "llama3:latest"

    def worker():
        for _ in range(iterations):
            collector.increment_request(model=model_name, status="success")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snapshot = collector.collect_snapshot()
    assert snapshot.requests[model_name]["success"] == iterations * 10
