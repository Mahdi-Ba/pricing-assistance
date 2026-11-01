# Source fixtures

Recorded responses replayed by the connector contract tests (`backend/tests/contract/`).

**Status: synthetic.** Except for `generic/`, which is purpose-built test content, every directory here holds a *synthetic* fixture. None of these sources had an access clearance when the connectors were written (business question Q-L1), so no real page or API response was fetched. Each fixture was written by hand to resemble the usual structure of that kind of page.

During the phase A qualification (`docs/runbooks/qualification.md`):

1. Record the real responses of every cleared source.
2. Replace the synthetic files here.
3. Adjust the extraction rule or connector config so the contract tests pass against the recordings.

Strip any personal data and secrets before committing. Until then, these tests prove only that the connectors honour the contract, not the real formats.
