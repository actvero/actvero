from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.modules.auth.oidc import IdentityProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("marker, enabled", [("unrelated", True), ("setup-marker", False)])
async def test_existing_email_cannot_be_adopted_or_password_reset(marker, enabled):
    provider = IdentityProvider(Settings(_env_file=None))
    provider.admin = AsyncMock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "existing",
                    "enabled": enabled,
                    "attributes": {"actvero_setup": [marker]},
                }
            ],
        )
    )
    with pytest.raises(HTTPException) as error:
        await provider.create_initial_user(
            "admin@example.test", "Admin", "password", "setup-marker"
        )
    assert error.value.status_code == 409
    assert [call.args[0] for call in provider.admin.call_args_list] == ["GET"]


@pytest.mark.asyncio
async def test_successful_remote_creation_can_be_recovered_without_changing_password():
    provider = IdentityProvider(Settings(_env_file=None))
    provider.admin = AsyncMock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "same-user",
                    "enabled": True,
                    "attributes": {"actvero_setup": ["setup-marker"]},
                }
            ],
        )
    )
    subject = await provider.create_initial_user(
        "admin@example.test", "Admin", "password", "setup-marker"
    )
    assert subject == "same-user"
    assert [call.args[0] for call in provider.admin.call_args_list] == ["GET"]


@pytest.mark.asyncio
async def test_provider_validation_body_is_not_exposed():
    provider = IdentityProvider(Settings(_env_file=None))
    rejection = httpx.Response(
        400,
        text="sensitive upstream error",
        request=httpx.Request("POST", "https://identity.test/users"),
    )
    provider.admin = AsyncMock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.HTTPStatusError("rejected", request=rejection.request, response=rejection),
        ]
    )
    with pytest.raises(HTTPException) as error:
        await provider.create_initial_user(
            "admin@example.test", "Admin", "password", "setup-marker"
        )
    assert error.value.status_code == 422
    assert "sensitive" not in error.value.detail
