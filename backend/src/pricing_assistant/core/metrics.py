"""Prometheus metrics shared across processes (design D13)."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

SCHEDULER_HEARTBEAT = Gauge(
    "pa_scheduler_heartbeat_timestamp_seconds",
    "Unix time of the last scheduler loop iteration",
    ["instance"],
)
SCHEDULER_IS_LEADER = Gauge(
    "pa_scheduler_is_leader", "1 if this scheduler instance holds the leader lock", ["instance"]
)
SCHEDULER_JOB_RUNS = Counter(
    "pa_scheduler_job_runs_total", "Scheduler job executions", ["job", "outcome"]
)
OUTBOX_LAG_SECONDS = Gauge("pa_outbox_lag_seconds", "Age of the oldest undispatched outbox event")
HTTP_REQUEST_SECONDS = Histogram(
    "pa_http_request_seconds", "HTTP request latency", ["method", "route", "status"]
)


def serve_metrics(port: int) -> bool:
    """Expose /metrics for a process without an HTTP server; no-op when ``port`` is 0."""
    if not port:
        return False
    start_http_server(port)
    return True
