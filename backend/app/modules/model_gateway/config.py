from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.core.outbound import endpoint


class NewApiGateway(BaseModel):
    """Provisioned by deployment operators, never selected by an HTTP caller."""

    base_url: str
    management_token: SecretStr

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        endpoint(value)
        if urlsplit(value).path not in {"", "/"}:
            raise ValueError("New API base URL must be an instance origin")
        return value.rstrip("/")


class NewApiConnection(NewApiGateway):
    """Legacy dedicated instance or a resolved organization bridge identity."""

    tenant_id: UUID
    namespace: str | None = None
    relay_key: SecretStr | None = None
    relay_token_id: int | None = Field(default=None, gt=0)
    relay_group: str = "default"
