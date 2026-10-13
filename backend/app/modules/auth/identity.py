from typing import Any

from sqlalchemy import case, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import LoginIdentity, User


async def resolve_identity(
    db: AsyncSession, issuer: str, claims: dict[str, Any]
) -> tuple[LoginIdentity, User]:
    subject = str(claims["sub"])
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:identity))"),
        {"identity": issuer + "|" + subject},
    )
    identity = await db.scalar(
        select(LoginIdentity).where(
            LoginIdentity.issuer == issuer, LoginIdentity.subject == subject
        )
    )
    if identity is None:
        user = User(
            name=str(claims.get("name") or claims.get("preferred_username") or "成员")[:200],
            email=claims.get("email"),
        )
        db.add(user)
        await db.flush()
        identity = LoginIdentity(user_id=user.id, issuer=issuer, subject=subject)
        db.add(identity)
        await db.flush()
    else:
        claim_name = claims.get("name") or claims.get("preferred_username")
        # Evaluate the local-name flag in the database, including concurrent profile saves.
        await db.execute(
            update(User)
            .where(User.id == identity.user_id)
            .values(
                name=case(
                    (User.name_managed_locally.is_(True), User.name),
                    else_=str(claim_name)[:200] if claim_name else User.name,
                ),
                email=claims.get("email"),
            )
        )
        existing_user = await db.get(User, identity.user_id, populate_existing=True)
        assert existing_user is not None
        user = existing_user
    identity.email_verified = claims.get("email_verified") is True
    return identity, user
