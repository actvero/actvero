"""Parse imports without returning or logging submitted secrets."""

from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.mcp.schemas import McpImportPreviewItem, McpServiceWrite, normalize_icon


def parse_import(
    configuration: dict[str, Any],
) -> list[tuple[McpImportPreviewItem, McpServiceWrite | None]]:
    if set(configuration) == {"mcpServers"} and isinstance(configuration["mcpServers"], dict):
        entries = list(configuration["mcpServers"].items())
        external = True
    elif set(configuration) == {"services"} and isinstance(configuration["services"], list):
        entries = [(str(i + 1), value) for i, value in enumerate(configuration["services"])]
        external = False
    else:
        raise HTTPException(422, "请提供 mcpServers 配置或 Actvero services 导出")
    if not 1 <= len(entries) <= 50:
        raise HTTPException(422, "每次导入 1–50 个服务")
    result: list[tuple[McpImportPreviewItem, McpServiceWrite | None]] = []
    names: set[str] = set()
    for fallback, raw in entries:
        preview = McpImportPreviewItem(name=fallback[:100], transport="—", auth_mode="none")
        item = None
        try:
            if not isinstance(raw, dict):
                raise ValueError("服务配置须为 JSON 对象")
            name = fallback if external else raw.get("name", fallback)
            preview.name = str(name)[:100]
            transport = raw.get("type", "http") if external else raw.get("transport", "http")
            if transport in ("http", "streamable-http"):
                transport = "http"
            preview.transport = str(transport)[:30]
            if "command" in raw or "env" in raw or transport not in ("http", "sse"):
                raise ValueError(
                    "当前仅支持 Streamable HTTP 和 SSE；不支持 STDIO、OpenAPI 或内置内容导入"
                )
            if external:
                if set(raw) - {"type", "url", "headers", "description"}:
                    raise ValueError("存在未支持的配置字段，请检查后重试")
                fields, values = [], {}
                headers = raw.get("headers", {})
                if not isinstance(headers, dict):
                    raise ValueError("headers 须为请求头对象")
                for index, (header, value) in enumerate(headers.items()):
                    if header.lower() == "content-type" and value == "application/json":
                        continue
                    if not isinstance(value, str):
                        raise ValueError("请求头值须为字符串")
                    key = f"credential_{index + 1}"
                    bearer = header.lower() == "authorization" and value.lower().startswith(
                        "bearer "
                    )
                    fields.append(
                        {
                            "key": key,
                            "label": "访问令牌" if bearer else header,
                            "header": header,
                            "bearer": bearer,
                        }
                    )
                    values[key] = value[7:] if bearer else value
                data = {
                    "name": name,
                    "transport": transport,
                    "url": raw.get("url", ""),
                    "description": raw.get("description", ""),
                    "auth_mode": "organization" if fields else "none",
                    "credential_fields": fields,
                    "credential_values": values if fields else None,
                }
            else:
                data = dict(raw)
            # Imported config never imports another instance's grants or enabled state.
            data.update(enabled=False, audience="organization", member_ids=[])
            item = McpServiceWrite.model_validate(data)
            item.icon = normalize_icon(item.icon)
            if item.name in names:
                raise ValueError("导入包含重名服务")
            names.add(item.name)
            preview.name = item.name
            preview.auth_mode = item.auth_mode
            preview.credential_count = len(item.credential_fields)
            preview.has_credentials = item.credential_values is not None
        except HTTPException as exc:
            preview.error = str(exc.detail)
            item = None
        except ValidationError:
            preview.error = "配置字段、服务地址或凭据格式无效，请检查原配置"
            item = None
        except ValueError as exc:
            preview.error = str(exc)
            item = None
        result.append((preview, item))
    return result
