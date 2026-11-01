# Adding a source connector

A connector turns one tracked offer (a product page or API item) into an **observation draft** or a **fetch failure**. Connectors never change anything at a source, never read prices with a language model, and never work around blocking.

## 1. Before writing code: clearance

A source can be fetched automatically only when **both** hold:

1. It has an unrevoked **access clearance**: approver, date, scope, reference and permitted request rate (`POST /api/v1/sources/{id}/clearances`).
2. Its status is `under_evaluation` or `approved`.

The runtime (`sources/runtime.py`) enforces this on every scheduled fetch, re-check and qualification run. The source's quota can never exceed the permitted rate. Revoking the clearance suspends the source.

**Not allowed, in any connector:**

- proxy rotation
- User-Agent or identity spoofing
- CAPTCHA solving
- headless tricks to look human
- following redirects to another domain

HTTP 403, HTTP 429 and challenge pages are `blocked`: they are not retried, and the source is paused for `Retry-After` (default 15 min). If a source blocks us, suspend it and talk to its owner.

## 2. Choose the retrieval method

| Method | Use when | Implementation |
|---|---|---|
| `api` | The source offers an official API under a contract | A class implementing `SourceConnector`, registered by `connector_key` |
| `html` | Prices are in the server-rendered HTML | No code. Use the generic page connector (`connector_key = generic_html`) plus an extraction rule |
| `rendered_page` | Prices appear only after JavaScript runs | Same generic connector; runs in `worker-browser`. Set `wait_for_selector` in the connector config |

Prefer `html` over `rendered_page`; browsers are slower and heavier. An `html` source never starts a browser.

## 3. The contract

```python
class SourceConnector(Protocol):
    key: str                     # matches source.connector_key
    method: RetrievalMethod      # api | html | rendered_page

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult: ...
```

- `OfferTarget` carries the URL or external ID, the source's currency unit and `base_domain`, and the own-store/own-channel flags.
- `FetchContext` carries:
  - the configured User-Agent and timeout,
  - the source's **active** extraction rule,
  - the non-secret connector config,
  - decrypted secrets. Its `repr` hides them; never log them.
- Return an `ObservationDraft` with one `ObservedOffer` per seller offer on the page:
  - `price_rial`: converted with `to_rial(amount, target.currency_unit)`,
  - `stock`, seller, title,
  - raw conditions (warranty, condition, payment),
  - identifiers (MPN/GTIN when available),
  - `Evidence`: raw HTML or JSON, the extracted JSON, and a screenshot for rendered pages.
- Or return a `FetchFailure(error_class, detail, http_status, retry_after_seconds)`. Only `network`, `timeout` and `http_error` (5xx) are retryable.
- **A failure is never an out-of-stock.** Report `out_of_stock` only from an explicit signal on a successful fetch.

### Page sources: extraction rules

Structured data (JSON-LD or microdata `Offer`) is read first. Otherwise the source's active selector rule applies:

```json
{
  "offer_container": ".seller-row",
  "price": {"selector": ".price"},
  "stock": {"selector": ".stock", "in_stock": ["موجود"], "out_of_stock": ["ناموجود"]},
  "seller": {"selector": ".seller-name"},
  "title": {"selector": "h1", "scope": "page"},
  "warranty": {"selector": ".warranty"},
  "payment": {"selector": ".payment"}
}
```

Rules are versioned data, not code:

1. Upload one or more sample pages: `POST /api/v1/sources/{id}/samples`.
2. Propose a rule: `POST /api/v1/sources/{id}/extraction-rules`. It is validated on every sample.
3. An admin approves it: `POST /api/v1/extraction-rules/{version}/review`. Only a rule that extracted offers from every sample can be approved. Approval retires the previous version.

## 4. Record fixtures

Save real responses captured during the phase A qualification under `fixtures/sources/<connector_key>/`:

- `*.html` or `*.json`: the raw responses,
- `*_rule.json`: the selector rule used with them (page sources).

Strip anything personal or secret before committing. The generic examples live in `fixtures/sources/generic/`.

## 5. Write contract tests

Create `backend/tests/contract/test_<connector_key>.py`. Replay fixtures through `httpx.MockTransport`, so tests never touch the live source:

```python
from tests.contract.harness import replay_registry, target_for, context_for

async def test_<connector_key>_extracts_offer() -> None:
    registry = replay_registry({"/p/1": "<connector_key>/product.html"})
    connector = registry.connector_for("<connector_key>", RetrievalMethod.HTML)
    result = await connector.fetch(target_for("https://shop.example/p/1"), context_for(rule))
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].price_rial == ...
```

Cover at least:

- a page with a price,
- an explicit out-of-stock page,
- a changed layout (must be `parse_failure`),
- a blocked response (must be `blocked`, not retryable).

`backend/tests/contract/test_generic_html.py` is the reference implementation of this template.

## 6. Register and wire

- **Page sources:** create the source with `connector_key = generic_html` and the right method. There is nothing to register.
- **API sources:** add the instance to `api_connectors` where the worker builds its `ConnectorRegistry` (`pricing_assistant/workers.py`), keyed by `connector_key`. Store credentials as connector secrets (`PUT /api/v1/sources/{id}/secrets/{name}`); they are write-only, so the API shows only whether a secret is set.

## 7. Qualify

Run the phase A qualification (`docs/runbooks/qualification.md`). The source reaches `approved` only after an admin reviews the report.
