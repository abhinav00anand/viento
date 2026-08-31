"""
SDK Job Scheduler and Worker Task Supervisor.

Enforces atomic queue insertion before JOB_ACK dispatch, unifies chat and embedding jobs
through concurrency semaphores, maintains job registry for queued cancellation, and delegates
execution handles to backend adapters.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from viento.backends.base import (
    EmbeddingResult,
    ExecutionHandle,
    GenerationChunk,
    InferenceBackend,
)

logger = logging.getLogger("viento.scheduler")


class JobType(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(BaseModel):
    """Represents a job queued for execution on the local runtime node."""

    job_id: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    job_type: JobType = JobType.CHAT
    status: JobStatus = JobStatus.QUEUED
    model: str
    messages: List[Dict[str, str]] = Field(default_factory=list)
    embedding_inputs: List[str] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 512
    stop: Optional[List[str]] = None
    queued_at: float = Field(default_factory=time.time)


class JobScheduler:
    """
    Local Job Scheduler managing FIFO queue, concurrency semaphores,
    and direct backend adapter execution.
    """

    def __init__(
        self,
        backend: InferenceBackend,
        connection_manager: Any,
        max_concurrency: int = 2,
        max_queue_depth: int = 50,
    ):
        self.backend = backend
        self.connection_manager = connection_manager
        self.max_concurrency = max_concurrency
        self.max_queue_depth = max_queue_depth

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue_depth)
        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        self._jobs: Dict[str, Job] = {}
        self._active_handles: Dict[str, ExecutionHandle] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start worker loop."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Stop worker loop, purge queue with task_done(), abort handles, and await task completion."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

        # Purge queued jobs safely using get_nowait() and task_done()
        while True:
            try:
                job: Job = self.queue.get_nowait()
                job.status = JobStatus.CANCELLED
                self._jobs.pop(job.job_id, None)
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        # Mark all jobs CANCELLED (if queued) or CANCEL_REQUESTED (if running)
        for job in list(self._jobs.values()):
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
            else:
                job.status = JobStatus.CANCEL_REQUESTED

        for handle in list(self._active_handles.values()):
            try:
                handle.cancel()
            except Exception:
                pass

        if self._active_tasks:
            await asyncio.gather(*list(self._active_tasks.values()), return_exceptions=True)

        if self._worker_task:
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def submit_job(self, envelope: Any) -> bool:
        """
        Atomic Enqueueing & Protocol-Compliant ACK:
          1. Check envelope & payload.
          2. Attempt queue.put_nowait(job).
          3. On QueueFull: send JOB_ERROR ("queue_full") and return False WITHOUT sending JOB_ACK.
          4. On success: send JOB_ACK.
        """
        payload_dict = envelope.payload
        job_id = envelope.job_id
        request_id = envelope.request_id

        if not job_id:
            logger.error("Received job envelope without job_id")
            return False

        is_embedding = (envelope.type == "embedding_request")
        job = Job(
            job_id=job_id,
            request_id=request_id,
            session_id=envelope.session_id,
            job_type=JobType.EMBEDDING if is_embedding else JobType.CHAT,
            model=payload_dict.get("model", ""),
            messages=payload_dict.get("messages", []),
            embedding_inputs=payload_dict.get("input", []),
            temperature=payload_dict.get("temperature", 0.7),
            max_tokens=payload_dict.get("max_tokens", 512),
            stop=payload_dict.get("stop"),
        )

        # Atomic Queue Enqueueing
        try:
            self.queue.put_nowait(job)
            self._jobs[job_id] = job
        except asyncio.QueueFull:
            logger.warning("Local job queue full (%d jobs). Rejecting job %s.", self.max_queue_depth, job_id)
            await self.connection_manager.send_job_error(
                job_id=job_id,
                error_message=f"Runtime queue full (max {self.max_queue_depth} jobs).",
                error_code="queue_full",
                request_id=request_id,
            )
            return False

        # Send JOB_ACK ONLY AFTER successful queue insertion
        await self.connection_manager.send_job_ack(
            job_id=job_id,
            request_id=request_id,
            queue_position=self.queue.qsize(),
        )
        return True

    def cancel_job(self, job_id: str) -> bool:
        """Cancel running or queued job via ExecutionHandle and JobStatus state machine."""
        found = False
        job = self._jobs.get(job_id)
        if job:
            found = True
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                logger.info("Marked queued job %s as CANCELLED.", job_id)
            elif job.status == JobStatus.RUNNING:
                job.status = JobStatus.CANCEL_REQUESTED
                logger.info("Marked running job %s as CANCEL_REQUESTED.", job_id)

        handle = self._active_handles.get(job_id)
        if handle:
            found = True
            handle.cancel()
        self.backend.cancel(job_id)
        return found

    async def _worker_loop(self) -> None:
        """Worker task popping jobs from queue and executing under semaphore."""
        while self._running:
            try:
                job: Job = await self.queue.get()
                task = asyncio.create_task(self._execute_job_wrapper(job))
                self._active_tasks[job.job_id] = task
                task.add_done_callback(lambda t, j_id=job.job_id: self._active_tasks.pop(j_id, None))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in scheduler worker loop: %s", exc)

    async def _execute_job_wrapper(self, job: Job) -> None:
        """Execute job under semaphore limits, checking cancellation state."""
        async with self.semaphore:
            if job.status in (JobStatus.CANCELLED, JobStatus.CANCEL_REQUESTED):
                logger.info("Skipping execution of cancelled job %s", job.job_id)
                job.status = JobStatus.CANCELLED
                self._jobs.pop(job.job_id, None)
                self.queue.task_done()
                return

            job.status = JobStatus.RUNNING
            try:
                if job.job_type == JobType.EMBEDDING:
                    await self._execute_embedding_job(job)
                else:
                    await self._execute_chat_job(job)
            finally:
                self._jobs.pop(job.job_id, None)
                self.queue.task_done()

    async def _execute_chat_job(self, job: Job) -> None:
        """Execute chat completion job."""
        loop = asyncio.get_running_loop()

        def token_callback(chunk: GenerationChunk) -> None:
            if job.status == JobStatus.CANCEL_REQUESTED:
                return
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_job_chunk(
                    job_id=job.job_id,
                    chunk=chunk.delta,
                    index=chunk.index,
                    request_id=job.request_id,
                ),
                loop,
            )

        def handle_created_callback(handle: ExecutionHandle) -> None:
            self._active_handles[job.job_id] = handle

        try:
            result, handle = await asyncio.to_thread(
                self.backend.generate,
                job_id=job.job_id,
                model=job.model,
                messages=job.messages,
                temperature=job.temperature,
                max_tokens=job.max_tokens,
                callback=token_callback,
                stop=job.stop,
                handle_callback=handle_created_callback,
            )

            if job.status == JobStatus.CANCEL_REQUESTED:
                job.status = JobStatus.CANCELLED
                logger.info("Job %s finished with CANCELLED state.", job.job_id)
                return

            job.status = JobStatus.COMPLETED

            await self.connection_manager.send_job_complete(
                job_id=job.job_id,
                result={
                    "finish_reason": result.finish_reason,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "total_tokens": result.total_tokens,
                    "is_estimated": result.is_estimated,
                },
                request_id=job.request_id,
            )
        except Exception as exc:
            if job.status == JobStatus.CANCEL_REQUESTED:
                job.status = JobStatus.CANCELLED
                logger.info("Job %s cancelled during stream execution.", job.job_id)
            else:
                job.status = JobStatus.FAILED
                logger.error("Execution failed for job %s: %s", job.job_id, exc)
                await self.connection_manager.send_job_error(
                    job_id=job.job_id,
                    error=str(exc),
                    request_id=job.request_id,
                )
        finally:
            self._active_handles.pop(job.job_id, None)

    async def _execute_embedding_job(self, job: Job) -> None:
        """Execute embedding job under unified queue & semaphore pipeline with early handle registration."""
        def handle_created_callback(handle: ExecutionHandle) -> None:
            self._active_handles[job.job_id] = handle

        try:
            if job.status == JobStatus.CANCEL_REQUESTED:
                job.status = JobStatus.CANCELLED
                return

            res: EmbeddingResult = await asyncio.to_thread(
                self.backend.embeddings,
                model=job.model,
                inputs=job.embedding_inputs,
                job_id=job.job_id,
                handle_callback=handle_created_callback,
            )

            if job.status == JobStatus.CANCEL_REQUESTED:
                job.status = JobStatus.CANCELLED
                logger.info("Embedding job %s finished with CANCELLED state.", job.job_id)
                return

            job.status = JobStatus.COMPLETED
            await self.connection_manager.send_embedding_response(
                job_id=job.job_id,
                model=job.model,
                embeddings=res.embeddings,
                prompt_tokens=res.prompt_tokens,
                total_tokens=res.total_tokens,
                is_estimated=res.is_estimated,
                request_id=job.request_id,
            )
        except Exception as exc:
            if job.status == JobStatus.CANCEL_REQUESTED:
                job.status = JobStatus.CANCELLED
                logger.info("Embedding job %s cancelled during execution.", job.job_id)
            else:
                job.status = JobStatus.FAILED
                logger.error("Embedding execution failed for job %s: %s", job.job_id, exc)
                await self.connection_manager.send_job_error(
                    job_id=job.job_id,
                    error=str(exc),
                    request_id=job.request_id,
                )
        finally:
            self._active_handles.pop(job.job_id, None)
