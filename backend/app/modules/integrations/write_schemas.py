from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.modules.experts.schemas import ExpertCheck, ExpertContent, ExpertInput
from app.modules.mcp.schemas import CredentialField, McpPresentation, McpServiceWrite

ResourceKind = Literal["mcp", "skills", "experts"]
SourceId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}$")]
Revision = Annotated[int, Field(ge=0, description="首次推送填 0，更新填当前资源修订号。")]


class McpResourceWrite(McpPresentation):
    revision: Revision
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    auth_mode: Literal["none", "personal"] = "none"
    credential_fields: list[CredentialField] = Field(default_factory=list, max_length=10)

    def service_input(self) -> McpServiceWrite:
        return McpServiceWrite(**self.model_dump(exclude={"revision"}))

    @model_validator(mode="after")
    def validate_service(self) -> Self:
        text = (
            self.name,
            self.description,
            self.display_name,
            *self.examples,
            *(field.label for field in self.credential_fields),
        )
        if any("\0" in value for value in text):
            raise ValueError("文本不能包含空字符")
        self.service_input()
        return self


class ExpertResourceWrite(ExpertInput):
    revision: Revision
    content: ExpertContent

    @model_validator(mode="after")
    def explicit_tools(self) -> Self:
        if any(ref.tools is None for ref in self.content.connectors):
            raise ValueError("MCP 依赖必须提供工具白名单")
        return self


class PushedSkillVersion(BaseModel):
    id: UUID
    version: str
    sha256: str


class ResourceWriteView(BaseModel):
    kind: ResourceKind
    source_id: str
    resource_id: UUID
    revision: int
    status: Literal["disabled", "enabled", "draft", "published", "superseded", "withdrawn"]
    current_release_id: UUID | None = None
    skill_version: PushedSkillVersion | None = None
    dependency_check: ExpertCheck | None = None
