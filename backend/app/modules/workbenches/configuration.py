from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from app.modules.workbenches.schemas import WorkbenchConfigField

_FIELDS = TypeAdapter(list[WorkbenchConfigField])


def valid_text(value: str) -> bool:
    return "\0" not in value and not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def validate_value(field: WorkbenchConfigField, value: str) -> None:
    if not value or not valid_text(value):
        raise ValueError(f"「{field.label}」包含空值或无效字符")
    if field.kind == "url":
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            if (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not any(char.isspace() or char == "\\" for char in value)
            ):
                return
        except ValueError:
            pass
        raise ValueError(f"「{field.label}」须填写有效的 HTTP 或 HTTPS 地址")


def parse_fields(data: object) -> list[WorkbenchConfigField]:
    if not isinstance(data, list) or len(data) > 32:
        raise ValueError("运行配置声明必须是数组，最多 32 项")
    try:
        fields = _FIELDS.validate_python(data)
    except ValidationError:
        raise ValueError("安装包的运行配置声明无效，请检查字段格式") from None
    if len({field.key for field in fields}) != len(fields):
        raise ValueError("安装包包含重复的运行配置 Key")
    for field in fields:
        if not valid_text(field.label) or not valid_text(field.description):
            raise ValueError("运行配置声明包含无效字符")
        if field.default is not None:
            validate_value(field, field.default)
    return fields


def resolve(fields: list[WorkbenchConfigField], stored: dict[str, str]) -> dict[str, str]:
    values = {}
    missing = []
    for field in fields:
        value = stored.get(field.key, field.default)
        if value is None:
            if field.required:
                missing.append(field.label)
        else:
            validate_value(field, value)
            values[field.key] = value
    if missing:
        raise ValueError("请填写必填运行配置：" + "、".join(missing))
    return values
