from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DepartmentGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: UUID
    include_descendants: bool = False


class DepartmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0, le=1000000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DepartmentUpdate(DepartmentInput):
    version: int = Field(ge=1)
    archived: bool = False


class DepartmentView(DepartmentInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    archived: bool
    version: int


class MemberDepartments(BaseModel):
    department_ids: list[UUID] = Field(default_factory=list, max_length=100)
    primary_department_id: UUID | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def primary_in_selection(self) -> "MemberDepartments":
        if len(set(self.department_ids)) != len(self.department_ids):
            raise ValueError("不能重复选择部门")
        if self.department_ids and self.primary_department_id not in self.department_ids:
            raise ValueError("请从所属部门中选择一个主部门")
        if not self.department_ids and self.primary_department_id is not None:
            raise ValueError("主部门必须属于所选部门")
        return self


class DepartmentScopePreview(BaseModel):
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    department_grants: list[DepartmentGrant] = Field(default_factory=list, max_length=100)
    page: int = Field(default=1, ge=1)


class DepartmentScopeMember(BaseModel):
    id: UUID
    name: str
    direct: bool
    department_ids: list[UUID]


class DepartmentScopePage(BaseModel):
    items: list[DepartmentScopeMember]
    total: int
    page: int
