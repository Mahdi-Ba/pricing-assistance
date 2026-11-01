"""Event consumers of the matching module (tasks 7.8, 8.1); run in ``worker-process``.

The handlers take the LLM port; with the default null adapter matching is purely rule-based.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.api import ObservationRow
from pricing_assistant.collection.events import ObservationRecorded
from pricing_assistant.core.consumer import Handler
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.llm.api import LLMPort
from pricing_assistant.matching.events import OfferAttributesUpdated
from pricing_assistant.matching.service import MarketOffer, evaluate, record_attributes


def observation_handler(llm: LLMPort | None = None) -> Handler:
    async def handle(session: AsyncSession, envelope: EventEnvelope) -> None:
        event = envelope.decode(ObservationRecorded)
        if event.is_own_store or event.is_own_channel:
            return  # our own listings are verification inputs, not competitor offers
        observations = (
            await session.scalars(
                select(ObservationRow).where(ObservationRow.id.in_(event.observation_ids))
            )
        ).all()
        for observation in observations:
            await record_attributes(session, envelope.tenant_id, observation, llm)

    return handle


def attributes_handler(llm: LLMPort | None = None) -> Handler:
    async def handle(session: AsyncSession, envelope: EventEnvelope) -> None:
        event = envelope.decode(OfferAttributesUpdated)
        await evaluate(
            session,
            envelope.tenant_id,
            MarketOffer(event.tracked_offer_id, event.seller_key),
            llm=llm,
        )

    return handle


on_observation_recorded = observation_handler()
on_attributes_updated = attributes_handler()
