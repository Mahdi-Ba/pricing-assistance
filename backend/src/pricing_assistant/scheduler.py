"""Scheduler composition root: leader-elected periodic jobs (outbox relay, due fetches, timers).

Run with ``python -m pricing_assistant.scheduler``. Several replicas may run; one leads.
"""

import asyncio
import signal
import socket

import dramatiq

from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.collection.retention import purge
from pricing_assistant.collection.scheduling import schedule_due
from pricing_assistant.core.broker import broker_dispatcher, create_broker
from pricing_assistant.core.db import Database, create_engine
from pricing_assistant.core.logging import configure_logging
from pricing_assistant.core.metrics import serve_metrics
from pricing_assistant.core.outbox import OutboxRelay
from pricing_assistant.core.registry import subscriptions_for
from pricing_assistant.core.scheduler import LeaderLock, ScheduledJob, Scheduler
from pricing_assistant.core.settings import Settings, get_settings
from pricing_assistant.core.tracing import configure_tracing
from pricing_assistant.decisions.api import mark_overdue
from pricing_assistant.pricing.consumers import refresh_aging
from pricing_assistant.wiring import consumer_specs, runtime
from pricing_assistant.workspace.sessions import close_idle

LOCK_NAME = "pricing-assistant.scheduler"


def build_jobs(
    db: Database,
    broker: dramatiq.Broker,
    maintenance_db: Database | None = None,
    evidence: EvidenceStore | None = None,
) -> list[ScheduledJob]:
    relay = OutboxRelay(db, broker_dispatcher(broker, subscriptions_for(consumer_specs())))

    async def due_fetches() -> int:
        return await schedule_due(db)

    recompute = runtime.recompute_scheduler()

    async def refresh() -> int:
        return await refresh_aging(db, recompute)

    async def overdue() -> int:
        return await mark_overdue(db)

    async def idle() -> int:
        return await close_idle(db)

    jobs = [
        ScheduledJob(name="outbox.relay", interval_seconds=1.0, run=relay.relay_once),
        ScheduledJob(name="collection.schedule_due", interval_seconds=30.0, run=due_fetches),
        ScheduledJob(name="pricing.refresh_aging", interval_seconds=300.0, run=refresh),
        ScheduledJob(name="decisions.verification_overdue", interval_seconds=60.0, run=overdue),
        ScheduledJob(name="workspace.close_idle_sessions", interval_seconds=300.0, run=idle),
    ]
    if maintenance_db is not None and evidence is not None:
        purge_db, store = maintenance_db, evidence

        async def retention() -> object:
            return await purge(purge_db, store)

        jobs.append(ScheduledJob(name="retention.purge", interval_seconds=3600.0, run=retention))
    return jobs


async def run(settings: Settings) -> None:
    db = Database(create_engine(settings.database_app_url, pool_size=4))
    maintenance_db = Database(create_engine(settings.database_maintenance_url, pool_size=1))
    broker = create_broker(settings)
    scheduler = Scheduler(
        LeaderLock(db.engine, LOCK_NAME),
        build_jobs(db, broker, maintenance_db, EvidenceStore(settings)),
        instance=socket.gethostname(),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await scheduler.run_forever(stop)
    finally:
        await db.dispose()
        await maintenance_db.dispose()
        broker.close()


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json, service="scheduler")
    configure_tracing(
        service=settings.service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint
    )
    serve_metrics(settings.metrics_port)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
