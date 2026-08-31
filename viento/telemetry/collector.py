"""Hardware telemetry collector, request counters, and latency histogram tracking."""

import asyncio
import logging
import math
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


@dataclass
class GPUStat:
    """Statistics for an individual NVIDIA GPU device."""

    index: int
    name: str
    gpu_util_percent: float
    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    temperature_c: Optional[float] = None
    power_draw_w: Optional[float] = None


@dataclass
class HardwareStats:
    """Aggregated hardware telemetry metrics snapshot."""

    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    cpu_count_logical: int = 1
    cpu_count_physical: int = 1
    memory_total_bytes: int = 0
    memory_used_bytes: int = 0
    memory_percent: float = 0.0
    gpus: Optional[List[GPUStat]] = None


@dataclass
class TelemetrySnapshot:
    """A point-in-time snapshot of telemetry metrics."""

    active_jobs_count: int
    hardware: HardwareStats
    requests: Dict[str, Dict[str, int]]
    latencies: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary format."""
        gpu_list = []
        if self.hardware.gpus:
            for g in self.hardware.gpus:
                gpu_list.append(
                    {
                        "index": g.index,
                        "name": g.name,
                        "gpu_util_percent": g.gpu_util_percent,
                        "memory_used_mb": g.memory_used_mb,
                        "memory_total_mb": g.memory_total_mb,
                        "memory_percent": g.memory_percent,
                        "temperature_c": g.temperature_c,
                        "power_draw_w": g.power_draw_w,
                    }
                )
        return {
            "timestamp": self.hardware.timestamp,
            "hardware": {
                "cpu": {
                    "percent": self.hardware.cpu_percent,
                    "logical_cores": self.hardware.cpu_count_logical,
                    "physical_cores": self.hardware.cpu_count_physical,
                },
                "ram": {
                    "total_bytes": self.hardware.memory_total_bytes,
                    "used_bytes": self.hardware.memory_used_bytes,
                    "percent": self.hardware.memory_percent,
                },
                "gpus": gpu_list,
            },
            "requests": self.requests,
            "latencies": self.latencies,
        }


class LatencyHistogram:
    """Thread-safe latency tracker calculating min, max, average, and p50/p90/p99 percentiles."""

    def __init__(self, max_samples: int = 10000):
        self.max_samples = max_samples
        self._samples: List[float] = []

    def record(self, latency_ms: float) -> None:
        """Records a latency value in milliseconds."""
        if math.isnan(latency_ms) or math.isinf(latency_ms) or latency_ms < 0:
            return
        if len(self._samples) >= self.max_samples:
            # Drop oldest 10% samples to keep memory bound
            drop_count = self.max_samples // 10
            self._samples = self._samples[drop_count:]
        self._samples.append(latency_ms)

    def summary(self) -> Dict[str, Any]:
        """Calculates statistical summary of recorded latencies."""
        if not self._samples:
            return {
                "count": 0,
                "sum_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p90_ms": 0.0,
                "p99_ms": 0.0,
            }

        sorted_vals = sorted(self._samples)
        count = len(sorted_vals)
        total_sum = sum(sorted_vals)

        def _percentile(p: float) -> float:
            k = (count - 1) * p
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return sorted_vals[int(k)]
            d0 = sorted_vals[int(f)] * (c - k)
            d1 = sorted_vals[int(c)] * (k - f)
            return d0 + d1

        return {
            "count": count,
            "sum_ms": round(total_sum, 2),
            "min_ms": round(sorted_vals[0], 2),
            "max_ms": round(sorted_vals[-1], 2),
            "avg_ms": round(total_sum / count, 2),
            "p50_ms": round(_percentile(0.50), 2),
            "p90_ms": round(_percentile(0.90), 2),
            "p99_ms": round(_percentile(0.99), 2),
        }

    def clear(self) -> None:
        self._samples.clear()


class TelemetryCollector:
    """Comprehensive hardware metrics and request telemetry collector."""

    def __init__(self):
        self._request_counters: Dict[str, Dict[str, int]] = {}  # model -> {status -> count}
        self._counter_lock = threading.Lock()
        self._latency_histograms: Dict[str, LatencyHistogram] = {}  # operation -> histogram
        self._nvidia_smi_path: Optional[str] = shutil.which("nvidia-smi")

    def get_cpu_metrics(self) -> Dict[str, Any]:
        """Collects CPU metrics using psutil with fallback."""
        try:
            percent = psutil.cpu_percent(interval=None)
            logical = psutil.cpu_count(logical=True) or 1
            physical = psutil.cpu_count(logical=False) or 1
            return {
                "cpu_percent": percent,
                "cpu_count_logical": logical,
                "cpu_count_physical": physical,
            }
        except Exception as e:
            logger.debug(f"psutil CPU metrics failed: {e}")
            return {
                "cpu_percent": 0.0,
                "cpu_count_logical": os.cpu_count() or 1,
                "cpu_count_physical": os.cpu_count() or 1,
            }

    def get_ram_metrics(self) -> Dict[str, Any]:
        """Collects RAM memory metrics using psutil with fallback."""
        try:
            mem = psutil.virtual_memory()
            return {
                "memory_total_bytes": mem.total,
                "memory_used_bytes": mem.used,
                "memory_available_bytes": mem.available,
                "memory_percent": mem.percent,
            }
        except Exception as e:
            logger.debug(f"psutil RAM metrics failed: {e}")
            return {
                "memory_total_bytes": 0,
                "memory_used_bytes": 0,
                "memory_available_bytes": 0,
                "memory_percent": 0.0,
            }

    @staticmethod
    def _safe_float(value: str, default: Optional[float] = 0.0) -> Optional[float]:
        """Safely parse float from nvidia-smi csv output, handling [N/A] and [Not Supported].

        Args:
            value: The string metric value from nvidia-smi output.
            default: Fallback float value if unparseable or unknown.

        Returns:
            The parsed float value, or the default value if parsing fails.
        """
        if not value or value.startswith("[") or value.lower() in ("n/a", "unknown"):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def get_gpu_metrics(self) -> Optional[List[GPUStat]]:
        """Collects GPU statistics via nvidia-smi subprocess query if available."""
        if not self._nvidia_smi_path:
            return None

        cmd = [
            self._nvidia_smi_path,
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=3.0)
            gpus = []
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    if not parts[0].isdigit():
                        logger.warning(
                            f"Skipping malformed nvidia-smi line with non-digit GPU index: '{line.strip()}'"
                        )
                        continue
                    idx = int(parts[0])
                    name = parts[1]
                    util = self._safe_float(parts[2], default=0.0)
                    mem_used = self._safe_float(parts[3], default=0.0)
                    mem_total = self._safe_float(parts[4], default=0.0)
                    temp = self._safe_float(parts[5], default=None) if len(parts) > 5 else None
                    power = self._safe_float(parts[6], default=None) if len(parts) > 6 else None

                    mem_percent = (mem_used / mem_total * 100.0) if mem_total > 0 else 0.0

                    gpus.append(
                        GPUStat(
                            index=idx,
                            name=name,
                            gpu_util_percent=util,
                            memory_used_mb=mem_used,
                            memory_total_mb=mem_total,
                            memory_percent=round(mem_percent, 2),
                            temperature_c=temp,
                            power_draw_w=power,
                        )
                    )
            return gpus if gpus else None
        except FileNotFoundError:
            # Log as INFO because this is a common and expected scenario on non-GPU systems.
            logger.info("nvidia-smi executable not found, skipping GPU metrics collection.")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi query timed out after 3.0 seconds.")
            return None
        except subprocess.CalledProcessError as e:
            err_msg = (
                e.stderr.decode(errors="ignore").strip()
                if isinstance(e.stderr, bytes)
                else str(e.stderr or "").strip()
            )
            logger.warning(f"nvidia-smi query failed with code {e.returncode}: {err_msg}")
            return None
        except Exception as e:
            # Catch-all for any other unexpected parsing or runtime errors.
            # Log as WARNING to ensure visibility for truly unexpected issues.
            logger.warning(f"Unexpected error querying nvidia-smi: {e}", exc_info=True)
            return None

    def get_hardware_stats(self) -> HardwareStats:
        """Returns HardwareStats data class snapshot."""
        cpu = self.get_cpu_metrics()
        ram = self.get_ram_metrics()
        gpus = self.get_gpu_metrics()

        return HardwareStats(
            timestamp=time.time(),
            cpu_percent=cpu["cpu_percent"],
            cpu_count_logical=cpu["cpu_count_logical"],
            cpu_count_physical=cpu["cpu_count_physical"],
            memory_total_bytes=ram["memory_total_bytes"],
            memory_used_bytes=ram["memory_used_bytes"],
            memory_percent=ram["memory_percent"],
            gpus=gpus,
        )

    def get_hardware_snapshot(self) -> HardwareStats:
        """Returns HardwareStats data class snapshot. Alias for get_hardware_stats."""
        return self.get_hardware_stats()

    async def get_gpu_metrics_async(self) -> Optional[List[GPUStat]]:
        """Asynchronously collects GPU statistics offloading subprocess execution to a worker thread."""
        return await asyncio.to_thread(self.get_gpu_metrics)

    async def get_hardware_stats_async(self) -> HardwareStats:
        """Asynchronously collects all hardware statistics without blocking the async event loop."""
        return await asyncio.to_thread(self.get_hardware_stats)

    def increment_request(self, model: str, status: str = "success") -> None:
        """Increments request counter for model and status in a thread-safe manner."""
        with self._counter_lock:
            if model not in self._request_counters:
                self._request_counters[model] = {}
            self._request_counters[model][status] = self._request_counters[model].get(status, 0) + 1

    def record_latency(self, operation: str, latency_ms: float) -> None:
        """Records latency for operation in latency histogram."""
        if operation not in self._latency_histograms:
            self._latency_histograms[operation] = LatencyHistogram()
        self._latency_histograms[operation].record(latency_ms)

    def collect_snapshot(self) -> TelemetrySnapshot:
        """Returns a snapshot of the current telemetry stats."""
        hw = self.get_hardware_stats()
        latencies = {op: hist.summary() for op, hist in self._latency_histograms.items()}
        with self._counter_lock:
            requests_copy = {
                model: dict(counts) for model, counts in self._request_counters.items()
            }
        return TelemetrySnapshot(
            active_jobs_count=0,
            hardware=hw,
            requests=requests_copy,
            latencies=latencies,
        )

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """Produces a JSON-serializable snapshot of hardware metrics, request counters, and latencies."""
        return self.collect_snapshot().to_dict()
