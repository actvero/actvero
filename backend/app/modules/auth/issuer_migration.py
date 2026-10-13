"""Explicit, quiescent issuer relocation backed by the same live realm and signing keys.

Never used in a login fallback; email is deliberately absent from this operation.
"""

import hashlib
import json
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import WebSession
from app.modules.auth.oidc import IdentityProvider
from app.modules.auth.service import now
from app.modules.desktop.models import DesktopLogin
from app.modules.users.models import LoginIdentity


def validate_relocation(source: str, target: str) -> None:
    if source == target:
        raise ValueError("Source and target must differ")
    for value in (source, target):
        parsed = urlsplit(value)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in {"https", "http"}
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})
            or "/realms/" not in parsed.path
            or value.endswith("/")
        ):
            raise ValueError("Invalid issuer relocation")
    if source.rsplit("/realms/", 1)[1] != target.rsplit("/realms/", 1)[1]:
        raise ValueError("Realm names must match")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def realm_proof(provider: IdentityProvider) -> dict[str, Any]:
    metadata = await provider.metadata()  # Exact configured issuer and endpoint checks.
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        result = await client.get(provider.internal(metadata["jwks_uri"]))
        result.raise_for_status()
        keys = result.json()["keys"]
    realm = (await provider.admin("GET", "")).json()
    if not realm.get("id") or not keys:
        raise ValueError("Missing realm/signing proof")
    return {"realm_id": realm["id"], "keys": sorted(fingerprint(key) for key in keys)}


async def rows(db: AsyncSession, issuer: str) -> list[dict[str, str]]:
    values = (
        await db.execute(
            select(LoginIdentity.id, LoginIdentity.user_id, LoginIdentity.subject)
            .where(LoginIdentity.issuer == issuer)
            .order_by(LoginIdentity.id)
        )
    ).all()
    return [
        {"id": str(row.id), "user_id": str(row.user_id), "subject": row.subject} for row in values
    ]


async def prepare(db: AsyncSession, provider: IdentityProvider, target: str) -> dict[str, Any]:
    source = provider.settings.oidc_issuer
    validate_relocation(source, target)
    proof = await realm_proof(provider)
    identities = await rows(db, source)
    if await rows(db, target):
        raise ValueError("Target issuer already has identities; no automatic merge")
    # Installation singleton exists before this feature's schema upgrade too.
    install = (
        await db.execute(text("SELECT issuer, subject FROM installation WHERE id=1"))
    ).first()
    if not install:
        raise ValueError("Installation is not initialized")
    return {
        "version": 1,
        "source": source,
        "target": target,
        "proof": proof,
        "identities": identities,
        "installation": {"issuer": install.issuer, "subject": install.subject},
    }


async def relocate(db: AsyncSession, provider: IdentityProvider, manifest: dict[str, Any]) -> str:
    source, target = manifest["source"], manifest["target"]
    validate_relocation(source, target)
    if manifest.get("version") != 1 or provider.settings.oidc_issuer != target:
        raise ValueError("Relocation manifest/configuration mismatch")
    actual = await realm_proof(provider)
    if actual["realm_id"] != manifest["proof"]["realm_id"] or not set(actual["keys"]).intersection(
        manifest["proof"]["keys"]
    ):
        raise ValueError("Different realm or signing authority; refusing relocation")
    for identity in manifest["identities"]:
        # Exact Keycloak subject confirmation, never an email match.
        response = await provider.admin("GET", "/users/" + quote(identity["subject"], safe=""))
        if response.json().get("id") != identity["subject"]:
            raise ValueError("Subject is not retained by this realm")
    # Operations happen only with the app stopped, and database locks make this explicit.
    await db.execute(
        text(
            "LOCK TABLE login_identities, installation, web_sessions, "
            "desktop_logins IN EXCLUSIVE MODE"
        )
    )
    old, new = await rows(db, source), await rows(db, target)
    install = (
        await db.execute(text("SELECT issuer, subject FROM installation WHERE id=1"))
    ).first()
    observed_install = {"issuer": install.issuer, "subject": install.subject} if install else None
    expected_install = dict(manifest["installation"])
    if expected_install["issuer"] == source:
        expected_install["issuer"] = target
    if not old and new == manifest["identities"] and observed_install == expected_install:
        return "already_applied"
    if old != manifest["identities"] or new:
        raise ValueError("Identity snapshot changed or target collision; re-preview required")
    if observed_install != manifest["installation"]:
        raise ValueError("Installation snapshot changed; re-preview required")
    ids = (await db.scalars(select(LoginIdentity.id).where(LoginIdentity.issuer == source))).all()
    await db.execute(
        update(LoginIdentity).where(LoginIdentity.issuer == source).values(issuer=target)
    )
    await db.execute(
        text("UPDATE installation SET issuer=:target WHERE id=1 AND issuer=:source"),
        {"source": source, "target": target},
    )
    # Existing Web tokens refer to the old issuer. Clear only credentials and pending attempts;
    # preserve account/member/tenant/device IDs, device tokens, deadlines and revocations.
    await db.execute(
        update(WebSession)
        .where(WebSession.identity_id.in_(ids))
        .values(
            tokens=None,
            authenticated_at=None,
            requires_reauth=True,
            login_state=None,
            login_data=None,
            login_expires_at=None,
        )
    )
    await db.execute(
        update(WebSession)
        .where(WebSession.identity_id.is_(None))
        .values(login_state=None, login_data=None, login_expires_at=None)
    )
    await db.execute(
        update(DesktopLogin)
        .where(DesktopLogin.consumed.is_(False))
        .values(cancelled=True, expires_at=now())
    )
    await db.commit()
    return "applied"
