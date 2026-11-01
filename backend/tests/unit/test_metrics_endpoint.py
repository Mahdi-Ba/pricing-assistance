"""Scheduler and worker processes expose Prometheus metrics on PA_METRICS_PORT."""

import socket
import urllib.request

from pricing_assistant.core.metrics import SCHEDULER_HEARTBEAT, serve_metrics


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_disabled_by_default() -> None:
    assert serve_metrics(0) is False


def test_serves_process_metrics() -> None:
    port = _free_port()
    SCHEDULER_HEARTBEAT.labels("test-instance").set(1_700_000_000)
    assert serve_metrics(port) is True
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
    assert 'pa_scheduler_heartbeat_timestamp_seconds{instance="test-instance"}' in body
