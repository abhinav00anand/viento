"""
Local Inference Benchmark Engine for Zephyr SDK.

Evaluates Time-to-First-Token (TTFT), Tokens-Per-Second (TPS), backpressure queue latency,
and backend adapter throughput.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List
from viento.backends.base import InferenceBackend


@dataclass
class BenchmarkReport:
    model: str
    backend: str
    iterations: int
    prompt_tokens: int
    completion_tokens: int
    total_time_seconds: float
    ttft_seconds: float
    tps: float
    latency_p50_ms: float
    latency_p99_ms: float
    success: bool
    error_message: str = ""


class BenchmarkSuite:
    """Benchmark suite for measuring local engine latency and token generation rates."""

    def __init__(self, backend: InferenceBackend):
        self.backend = backend

    def run_chat_benchmark(
        self,
        model: str,
        prompt: str = "Explain quantum computing in 50 words.",
        iterations: int = 3,
        max_tokens: int = 128,
    ) -> BenchmarkReport:
        """Run chat completion benchmark and record TTFT & TPS metrics."""
        latencies: List[float] = []
        first_token_times: List[float] = []
        total_completion_tokens = 0
        total_prompt_tokens = 0
        start_overall = time.time()

        for idx in range(iterations):
            t0 = time.time()
            ttft: float = 0.0
            first_chunk_received = False
            token_count = 0

            def on_chunk(chunk):
                nonlocal ttft, first_chunk_received, token_count
                if not first_chunk_received:
                    ttft = time.time() - t0
                    first_chunk_received = True
                token_count += 1

            messages = [{"role": "user", "content": prompt}]
            try:
                res, _ = self.backend.generate(
                    job_id=f"bm_{idx}",
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    callback=on_chunk,
                )
                elapsed = time.time() - t0
                latencies.append(elapsed * 1000.0)
                if first_chunk_received:
                    first_token_times.append(ttft)
                total_completion_tokens += res.completion_tokens
                total_prompt_tokens += res.prompt_tokens
            except Exception as exc:
                return BenchmarkReport(
                    model=model,
                    backend=self.backend.name(),
                    iterations=iterations,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_time_seconds=time.time() - start_overall,
                    ttft_seconds=0.0,
                    tps=0.0,
                    latency_p50_ms=0.0,
                    latency_p99_ms=0.0,
                    success=False,
                    error_message=str(exc),
                )

        total_elapsed = time.time() - start_overall
        avg_ttft = (sum(first_token_times) / len(first_token_times)) if first_token_times else 0.0
        tps = (total_completion_tokens / total_elapsed) if total_elapsed > 0 else 0.0

        latencies.sort()
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p99 = latencies[-1] if latencies else 0.0

        return BenchmarkReport(
            model=model,
            backend=self.backend.name(),
            iterations=iterations,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_time_seconds=total_elapsed,
            ttft_seconds=avg_ttft,
            tps=tps,
            latency_p50_ms=p50,
            latency_p99_ms=p99,
            success=True,
        )
