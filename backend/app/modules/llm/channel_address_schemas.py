"""Credential-free input for the pure address preview API."""

from pydantic import Field

from app.modules.llm.providers.connection import AddressMode, ChannelConnection, Operation
from app.modules.llm.schemas import Input, ProviderId


class AddressConnection(Input):
    address_mode: AddressMode
    service_root: str | None = Field(default=None, max_length=2000)
    api_prefix: str | None = Field(default=None, max_length=200)
    legacy_base_url: str | None = Field(default=None, max_length=2000)
    resolver_version: int = Field(default=1, ge=1)

    def connection(self) -> ChannelConnection:
        return ChannelConnection(**self.model_dump())


class ChannelAddressInput(Input):
    provider: ProviderId
    connection: AddressConnection
    model: str | None = Field(default=None, min_length=1, max_length=200)
    operations: tuple[Operation, ...] | None = Field(default=None, max_length=5)
    stream: bool = False
