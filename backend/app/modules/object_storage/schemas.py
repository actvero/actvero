from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.modules.object_storage.validation import Input, https_url


class StorageSave(Input):
    expected_revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=100)
    endpoint: str = Field(max_length=2048)
    region: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")
    bucket: str = Field(min_length=3, max_length=200, pattern=r"^[a-zA-Z0-9._-]+$")
    prefix: str = Field(
        default="actvero", max_length=200, pattern=r"^[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*$"
    )
    public_url: str = Field(default="", max_length=2048)
    path_style: bool = False
    access_key: SecretStr | None = Field(default=None, min_length=1, max_length=500)
    secret_key: SecretStr | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool = True
    is_default: bool = False

    @field_validator("endpoint", "public_url")
    @classmethod
    def address(cls, value: str, info: ValidationInfo) -> str:
        if not value and info.field_name == "public_url":
            return value
        value = https_url(value).rstrip("/")
        if urlsplit(value).query:
            raise ValueError("存储地址不能包含查询参数")
        return value

    @model_validator(mode="after")
    def credentials_pair(self) -> "StorageSave":
        if bool(self.access_key) != bool(self.secret_key):
            raise ValueError("请同时提供访问密钥和秘密密钥")
        if self.is_default and not self.enabled:
            raise ValueError("默认存储必须启用")
        return self


class StorageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    endpoint: str
    region: str
    bucket: str
    prefix: str
    public_url: str
    path_style: bool
    enabled: bool
    is_default: bool
    revision: int
