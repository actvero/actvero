"""Deployment gateway secrets must never become implicit test connections."""

import pytest


@pytest.fixture(autouse=True)
def isolated_gateway_configuration(monkeypatch):
    # Some provider dependencies load dotenv during import. Tests must opt into
    # a disposable engine through ACTVERO_TEST_* rather than the running app.
    for key in (
        "ACTVERO_NEWAPI_CONNECTIONS",
        "ACTVERO_NEWAPI_GATEWAY",
        "ACTVERO_NEWAPI_BASE_URL",
        "ACTVERO_NEWAPI_MANAGEMENT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
