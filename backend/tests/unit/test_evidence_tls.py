"""Object-storage TLS options for the split collector topology (task 14.3)."""

from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.core.settings import Settings


def test_client_certificate_and_ca_bundle_are_passed_to_the_s3_client() -> None:
    store = EvidenceStore(
        Settings(
            s3_endpoint_url="https://s3.internal:9000",
            s3_ca_bundle="/etc/pa-tls/ca.crt",
            s3_client_cert="/etc/pa-tls/tls.crt",
            s3_client_key="/etc/pa-tls/tls.key",
        )
    )
    client = store._client
    assert client.meta.config.client_cert == ("/etc/pa-tls/tls.crt", "/etc/pa-tls/tls.key")
    assert client._endpoint.http_session._verify == "/etc/pa-tls/ca.crt"


def test_defaults_verify_with_system_roots_and_no_client_certificate() -> None:
    client = EvidenceStore(Settings())._client
    assert client.meta.config.client_cert is None
    assert client._endpoint.http_session._verify is True
