import asyncio
from typing import cast

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.core.database import Database

router = APIRouter(prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "actvero-platform"
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse, operation_id="get_health", tags=["system"])
async def health() -> HealthResponse:
    """Liveness only: this does not imply authentication or business modules are ready."""
    return HealthResponse()


@router.get(
    "/ready", response_model=ReadinessResponse, operation_id="get_readiness", tags=["system"]
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    database = cast(Database, request.app.state.database)
    try:
        connected = await asyncio.wait_for(database.ping(), timeout=3)
    except Exception:
        connected = False
    if not connected:
        response.status_code = 503
    return ReadinessResponse(
        status="ready" if connected else "not_ready",
        database="connected" if connected else "unavailable",
    )
