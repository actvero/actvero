from fastapi import Request

from app.modules.auth.service import DB, authenticate
from app.modules.users.models import User


async def require_identity(request: Request, db: DB) -> User:
    """Resolve an authenticated identity; domain routes also validate tenant membership."""
    _, _, user = await authenticate(request, db)
    return user
