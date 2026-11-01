"""Event consumers of the decisions module (task 10.5); run in ``worker-process``."""

from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.events import ObservationRecorded
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.decisions.service import verify_from_observations


async def on_observation_recorded(session: AsyncSession, envelope: EventEnvelope) -> None:
    """Our own store or channel listing was observed: check reported price changes against it."""
    event = envelope.decode(ObservationRecorded)
    if not (event.is_own_store or event.is_own_channel):
        return
    await verify_from_observations(
        session,
        tenant_id=envelope.tenant_id,
        variant_id=event.variant_id,
        observation_ids=event.observation_ids,
        own_store=event.is_own_store,
        own_channel=event.is_own_channel,
    )
