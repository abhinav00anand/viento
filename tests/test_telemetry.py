"""Unit tests for telemetry collector, latency histograms, and secret-masking logger."""

import json
import logging
import pytest

from viento.telemetry.collector import (
    LatencyHistogram,
    TelemetryCollector,
    HardwareStats,
)
from viento.telemetry.logging import (
    ConsoleFormatter,
    SecretMasker,
    StructuredJsonFormatter,
    get_logger,
)


def test_latency_histogram_empty():
    hist = LatencyHistogram()
    summary = hist.summary()
    assert summary["count"] == 0
    assert summary["min_ms"] == 0.0
    assert summary["max_ms"] == 0.0
    assert summary["p50_ms"] == 0.0


def test_latency_histogram_calculations():
    hist = LatencyHistogram()
    # Add values 10, 20, 30, 40, 50, 60, 70, 80, 90, 100
    for val in range(10, 110, 10):
        hist.record(float(val))

    summary = hist.summary()
    assert summary["count"] == 10
    assert summary["min_ms"] == 10.0
    assert summary["max_ms"] == 100.0
    assert summary["avg_ms"] == 55.0
    assert summary["p50_ms"] == 55.0
    assert summary["p90_ms"] == 91.0 or summary["p90_ms"] > 80.0
    assert summary["p99_ms"] >= 99.0


def test_telemetry_collector_hardware_metrics():
    collector = TelemetryCollector()

    cpu = collector.get_cpu_metrics()
    assert "cpu_percent" in cpu
    assert cpu["cpu_count_logical"] >= 1

    ram = collector.get_ram_metrics()
    assert "memory_total_bytes" in ram
    assert "memory_percent" in ram

    hw_stats = collector.get_hardware_stats()
    assert isinstance(hw_stats, HardwareStats)
    assert hw_stats.timestamp > 0


def test_telemetry_collector_counters_and_snapshot():
    collector = TelemetryCollector()

    collector.increment_request("llama3", "success")
    collector.increment_request("llama3", "success")
    collector.increment_request("llama3", "error")
    collector.increment_request("mistral", "success")

    collector.record_latency("inference", 45.2)
    collector.record_latency("inference", 120.0)

    snapshot = collector.get_metrics_snapshot()
    assert "hardware" in snapshot
    assert "requests" in snapshot
    assert "latencies" in snapshot

    reqs = snapshot["requests"]
    assert reqs["llama3"]["success"] == 2
    assert reqs["llama3"]["error"] == 1
    assert reqs["mistral"]["success"] == 1

    lat = snapshot["latencies"]["inference"]
    assert lat["count"] == 2
    assert lat["min_ms"] == 45.2
    assert lat["max_ms"] == 120.0


def test_secret_masker_patterns():
    # Test zph_tmp_ secret masking
    text1 = "Connecting with key zph_tmp_abc123456789xyz"
    masked1 = SecretMasker.mask(text1)
    assert "zph_tmp_****" in masked1
    assert "abc123456789xyz" not in masked1

    # Test zph_live_ secret masking
    text2 = "Live token is zph_live_sec998877665544"
    masked2 = SecretMasker.mask(text2)
    assert "zph_live_****" in masked2
    assert "sec998877665544" not in masked2

    # Test OpenAI API key masking
    text3 = "OpenAI key sk-1234567890abcdef123456"
    masked3 = SecretMasker.mask(text3)
    assert "sk-****" in masked3
    assert "1234567890abcdef123456" not in masked3

    # Test Authorization Bearer token masking
    text4 = "Header Authorization: Bearer eyJhbGciOiJIUzI1NiIn..."
    masked4 = SecretMasker.mask(text4)
    assert "Bearer [REDACTED]" in masked4

    # Test key-value secret masking
    text5 = "config options: password='super_secret_pass', api_key=\"zph_tmp_99\""
    masked5 = SecretMasker.mask(text5)
    assert "password=[REDACTED]" in masked5
    assert "api_key=[REDACTED]" in masked5


def test_structured_json_formatter():
    formatter = StructuredJsonFormatter(service_name="test-service")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Authenticated user with token zph_tmp_secrettoken123",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)

    parsed = json.loads(formatted)
    assert parsed["level"] == "INFO"
    assert parsed["service"] == "test-service"
    assert "zph_tmp_****" in parsed["message"]
    assert "secrettoken123" not in parsed["message"]


def test_console_formatter():
    formatter = ConsoleFormatter(use_colors=False)
    record = logging.LogRecord(
        name="test_console",
        level=logging.WARNING,
        pathname="test.py",
        lineno=10,
        msg="Warning: password='my_password'",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)

    assert "WARNING" in formatted
    assert "password=[REDACTED]" in formatted
    assert "my_password" not in formatted


def test_get_logger_factory():
    logger_inst = get_logger(name="zephyr_test_unique", log_level="DEBUG", json_output=True)
    assert logger_inst.name == "zephyr_test_unique"
    assert logger_inst.level == logging.DEBUG
    assert len(logger_inst.handlers) == 1
    assert isinstance(logger_inst.handlers[0].formatter, StructuredJsonFormatter)
