"""Retry presentation synchronization independently of login and publication."""

import asyncio
import logging
from html import escape

from fastapi import FastAPI
from sqlalchemy import select

from app.core.database import Database
from app.modules.auth.oidc import IdentityProvider
from app.modules.platform.branding import public_branding
from app.modules.tenants.models import Installation

logger = logging.getLogger(__name__)


async def sync_identity(database: Database, identity: IdentityProvider) -> bool:
    async with database.sessions() as db:
        # Serializes publication and competing workers. A failed/uncertain remote
        # write leaves the revision pending; repeating this update is idempotent.
        install = await db.scalar(
            select(Installation).where(Installation.id == 1).with_for_update()
        )
        if install is None or install.identity_branding_revision == install.branding_revision:
            return False
        brand = public_branding(identity.settings.app_url, install)
        remote = (await identity.admin("GET", "")).json()
        attributes = dict(remote.get("attributes") or {})
        attributes.update(
            {
                "actveroBrandRevision": str(brand.revision),
                "actveroBrandFavicon": brand.favicon_url,
                "actveroBrandAppleIcon": brand.apple_icon_url,
            }
        )
        for slot in ("mark_light", "mark_dark", "wordmark_light", "wordmark_dark"):
            attributes["actveroBrand_" + slot] = brand.assets.get(slot, "")
        smtp = dict(remote.get("smtpServer") or {})
        if smtp:
            smtp["fromDisplayName"] = brand.name
        await identity.admin(
            "PUT",
            "",
            json={
                "displayName": brand.name,
                "displayNameHtml": escape(brand.name),
                "attributes": attributes,
                "emailTheme": "actvero",
                **({"smtpServer": smtp} if smtp else {}),
            },
        )
        install.identity_branding_revision = install.branding_revision
        await db.commit()
        return True


async def monitor_branding(app: FastAPI) -> None:
    while True:
        try:
            async with asyncio.timeout(8):
                await sync_identity(app.state.database, app.state.identity_provider)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Never print administrative request/response bodies or mail secrets.
            logger.warning("Brand identity synchronization pending (%s)", type(error).__name__)
        await asyncio.sleep(15)
