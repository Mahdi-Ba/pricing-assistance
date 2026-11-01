import uuid
from datetime import UTC, datetime

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.connector import (
    Evidence,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    ObservationDraft,
    ObservedOffer,
    OfferTarget,
    SourceConnector,
    StockState,
)
from pricing_assistant.sources.models import RetrievalMethod

TARGET = OfferTarget(
    tracked_offer_id=uuid.uuid4(),
    source_id=uuid.uuid4(),
    variant_id=uuid.uuid4(),
    url="https://shop.test/p/1",
    external_id=None,
    currency_unit=CurrencyUnit.TOMAN,
    base_domain="shop.test",
)
CTX = FetchContext(
    tenant_id=uuid.uuid4(),
    correlation_id="corr-test-0001",
    user_agent="TunooPricingBot/0.1",
    timeout_seconds=5,
    secrets={"api_token": "s3cr3t"},
)


class FakeConnector:
    key = "fake"
    method = RetrievalMethod.HTML

    def __init__(self, result: FetchResult) -> None:
        self.result = result

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        return self.result


def _accepts(connector: SourceConnector) -> SourceConnector:
    return connector


async def test_fake_connector_conforms_to_protocol() -> None:
    draft = ObservationDraft(
        target=TARGET,
        observed_at=datetime.now(UTC),
        method=RetrievalMethod.HTML,
        offers=[ObservedOffer(price_rial=860_000_000, stock=StockState.IN_STOCK, seller="Lion")],
        evidence=Evidence(html=b"<html></html>"),
    )
    connector = _accepts(FakeConnector(draft))
    assert isinstance(connector, SourceConnector)
    assert await connector.fetch(TARGET, CTX) is draft


def test_only_transient_failures_are_retryable() -> None:
    assert FetchFailure(FetchErrorClass.HTTP_ERROR, "503", http_status=503).retryable
    assert FetchFailure(FetchErrorClass.TIMEOUT, "slow").retryable
    assert not FetchFailure(FetchErrorClass.BLOCKED, "429", http_status=429).retryable
    assert not FetchFailure(FetchErrorClass.PARSE_FAILURE, "no price").retryable


def test_fetch_context_repr_hides_secret_values() -> None:
    assert "s3cr3t" not in repr(CTX)
    assert "api_token" in repr(CTX)
