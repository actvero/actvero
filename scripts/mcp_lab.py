"""Loopback-only MCP acceptance lab. Uses synthetic, deterministic, read-only data.

Run: uv run --frozen --directory backend python ../scripts/mcp_lab.py
Test: uv run --frozen --directory backend python ../scripts/mcp_lab.py --verify
"""

import argparse
import asyncio
import base64
import hmac
import json
from typing import Annotated

import httpx
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.prompts import Message
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools import ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent
from pydantic import Field
from starlette.responses import JSONResponse

DOCUMENTS = {
    "onboarding": {
        "title": "新同事入职指南（示例）",
        "body": ("周一领取电脑，周二完成账号培训，周三与导师确认首周计划。联系人：示例导师。"),
        "tags": ["入职", "人事"],
    },
    "travel": {
        "title": "差旅报销说明（示例）",
        "body": (
            "出差前登记行程，返程后五个工作日内提交示例发票和差旅说明。此为验收数据，不是真实制度。"
        ),
        "tags": ["差旅", "报销"],
    },
    "release": {
        "title": "九月交付记录（示例）",
        "body": ("已完成：连接器目录、文档搜索。待验证：提示词、资源模板。下一步：执行联调验收。"),
        "tags": ["研发", "周报"],
    },
}
BINARY = b"DS MCP lab binary fixture\x00\x01\xff"
ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
ENDPOINTS = [
    ("HTTP", "http://127.0.0.1:5291/mcp"),
    ("SSE", "http://127.0.0.1:5292/sse"),
]


# Deliberately public test values, not credentials for any real system.
# They authorize only this loopback lab's synthetic data.
LAB_IDENTITIES = {"ds-lab-alice": "Alice（示例）", "ds-lab-bob": "Bob（示例）"}


class LabBearerAuth:
    """Require a known test bearer on every request, including initialize/list."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            authorization = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not any(
                hmac.compare_digest(authorization, f"Bearer {token}".encode())
                for token in LAB_IDENTITIES
            ):
                response = JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="ds-local-lab"'},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_server(label: str, authenticated: bool = False) -> FastMCP:
    server = FastMCP(f"DS 本地验收 · {label}")

    @server.tool(title="搜索示例文档", annotations=ANNOTATIONS)
    def search_documents(query: str, limit: Annotated[int, Field(ge=1, le=10)] = 5) -> dict:
        """搜索本地示例资料。支持中文，返回文档标识、标题和可读取的资源 URI。"""
        matches = [
            {"id": key, "title": doc["title"], "uri": f"lab://documents/{key}"}
            for key, doc in DOCUMENTS.items()
            if query.casefold() in json.dumps(doc, ensure_ascii=False).casefold()
        ]
        return {"matches": matches[:limit], "total": len(matches), "source": label}

    @server.tool(title="读取示例文档", annotations=ANNOTATIONS)
    def get_document(document_id: str) -> ToolResult:
        """按 onboarding、travel 或 release 读取文档。未知文档返回标准 isError。"""
        if document_id not in DOCUMENTS:
            return ToolResult(
                content=[TextContent(type="text", text="LAB_NOT_FOUND: 未找到示例文档")],
                is_error=True,
            )
        document = {"id": document_id, **DOCUMENTS[document_id]}
        return ToolResult(
            content=[TextContent(type="text", text=document["body"])],
            structured_content=document,
        )

    @server.tool(title="计算示例合计", annotations=ANNOTATIONS)
    def sum_numbers(
        numbers: Annotated[list[float], Field(min_length=1, max_length=100)],
    ) -> dict:
        """计算最多 100 个数字的总和，用于验证数组参数和结构化结果。"""
        return {"count": len(numbers), "total": sum(numbers)}

    @server.tool(title="模拟业务错误", annotations=ANNOTATIONS)
    def simulate_error() -> ToolResult:
        """明确要求测试错误时才使用。固定返回 LAB_EXPECTED_ERROR，不执行任何外部操作。"""
        return ToolResult(
            content=[TextContent(type="text", text="LAB_EXPECTED_ERROR: 这是预期的验收错误")],
            structured_content={"code": "LAB_EXPECTED_ERROR", "retryable": False},
            is_error=True,
        )

    @server.tool(title="等待后返回", annotations=ANNOTATIONS)
    async def wait_and_echo(
        message: str, seconds: Annotated[float, Field(ge=0, le=3)] = 0.1
    ) -> dict:
        """等待最多三秒并原样返回示例消息，用于检查异步调用。"""
        await asyncio.sleep(seconds)
        return {"message": message, "seconds": seconds}

    @server.prompt(title="生成文档摘要")
    def summarize_document(document_id: str, style: str = "简洁") -> list[Message]:
        """为示例文档生成摘要提示词，document_id 必填，style 可选。"""
        if document_id not in DOCUMENTS:
            raise ValueError("LAB_NOT_FOUND")
        return [
            Message(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        f"请用{style}风格总结以下示例文档，并标注这是测试资料。\n"
                        f"{DOCUMENTS[document_id]['title']}\n{DOCUMENTS[document_id]['body']}"
                    ),
                ),
            )
        ]

    @server.prompt(title="整理示例周报")
    def weekly_report(team: str, week: str = "本周") -> list[Message]:
        """两个消息组成的提示词，验证必填参数、默认参数和消息顺序。"""
        return [
            Message(
                role="user",
                content=TextContent(type="text", text=f"请为{team}整理{week}周报。"),
            ),
            Message(
                role="user",
                content=TextContent(type="text", text=DOCUMENTS["release"]["body"]),
            ),
        ]

    @server.resource("lab://guide", name="lab_guide", title="验收说明", mime_type="text/markdown")
    def guide() -> str:
        return "# DS MCP 验收资料\n仅包含示例内容。支持工具、提示词、固定资源和资源模板。\n"

    @server.resource(
        "lab://catalog",
        name="lab_catalog",
        title="示例资料目录",
        mime_type="application/json",
    )
    def catalog() -> str:
        return json.dumps(DOCUMENTS, ensure_ascii=False)

    @server.resource(
        "lab://binary",
        name="lab_binary",
        title="二进制验收样本",
        mime_type="application/octet-stream",
    )
    def binary() -> bytes:
        return BINARY

    @server.resource(
        "lab://documents/{document_id}",
        name="lab_document",
        title="按标识读取文档",
        mime_type="text/markdown",
    )
    def document_resource(document_id: str) -> str:
        if document_id not in DOCUMENTS:
            raise ValueError("LAB_NOT_FOUND")
        doc = DOCUMENTS[document_id]
        return f"# {doc['title']}\n\n{doc['body']}"

    @server.resource(
        "lab://reports/{team}/{week}",
        name="lab_report",
        title="团队周报模板",
        mime_type="application/json",
    )
    def report_resource(team: str, week: str) -> str:
        return json.dumps(
            {
                "team": team,
                "week": week,
                "completed": 3,
                "pending": 2,
                "synthetic": True,
            },
            ensure_ascii=False,
        )

    if authenticated:

        @server.tool(title="核验示例身份", annotations=ANNOTATIONS)
        def who_am_i() -> dict:
            """返回当前上游测试凭据对应的示例身份，不返回凭据本身。"""
            authorization = get_http_headers(include={"authorization"}).get("authorization", "")
            return {
                "name": LAB_IDENTITIES.get(authorization.removeprefix("Bearer "), "unknown"),
                "synthetic": True,
            }

    return server


async def serve() -> None:
    servers = []
    for label, port, transport in [
        ("HTTP", 5291, "http"),
        ("SSE", 5292, "sse"),
        ("AUTH", 5293, "http"),
    ]:
        app = create_server(label, authenticated=label == "AUTH").http_app(
            transport=transport, stateless_http=transport == "http"
        )
        if label == "AUTH":
            app = LabBearerAuth(app)
        servers.append(
            uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    access_log=False,
                    log_level="warning",
                )
            )
        )
    print("DS MCP lab starting: HTTP 5291/mcp; SSE 5292/sse; Bearer 5293/mcp", flush=True)
    # One process owns both listeners; SIGINT/SIGTERM shuts both down.
    await asyncio.gather(*(server.serve() for server in servers))


async def verify() -> None:
    for label, url in ENDPOINTS:
        checks = 0
        async with Client(url, timeout=15) as client:
            assert len(await client.list_tools()) == 5
            assert len(await client.list_prompts()) == 2
            assert len(await client.list_resources()) == 3
            assert len(await client.list_resource_templates()) == 2
            checks += 4
            result = await client.call_tool("search_documents", {"query": "入职"})
            assert result.structured_content["matches"][0]["id"] == "onboarding"
            assert (
                await client.call_tool("search_documents", {"query": "不存在"})
            ).structured_content["total"] == 0
            assert (
                await client.call_tool("get_document", {"document_id": "travel"})
            ).structured_content["id"] == "travel"
            assert (
                await client.call_tool("sum_numbers", {"numbers": [1, 2, 3.5]})
            ).structured_content["total"] == 6.5
            assert (
                await client.call_tool("wait_and_echo", {"message": "你好"})
            ).structured_content["message"] == "你好"
            checks += 5
            for name, arguments in [
                ("simulate_error", {}),
                ("get_document", {"document_id": "missing"}),
                ("sum_numbers", {"numbers": []}),
            ]:
                assert (await client.call_tool(name, arguments, raise_on_error=False)).is_error
                checks += 1
            assert (
                "入职"
                in (await client.get_prompt("summarize_document", {"document_id": "onboarding"}))
                .messages[0]
                .content.text
            )
            prompt = await client.get_prompt(
                "weekly_report", {"team": "测试组", "week": "2026-W39"}
            )
            assert len(prompt.messages) == 2 and "2026-W39" in prompt.messages[0].content.text
            checks += 2
            assert "验收资料" in (await client.read_resource("lab://guide"))[0].text
            assert "travel" in json.loads((await client.read_resource("lab://catalog"))[0].text)
            assert base64.b64decode((await client.read_resource("lab://binary"))[0].blob) == BINARY
            assert "报销" in (await client.read_resource("lab://documents/travel"))[0].text
            assert (
                json.loads((await client.read_resource("lab://reports/demo/2026-W39"))[0].text)[
                    "completed"
                ]
                == 3
            )
            checks += 5
            for operation in [
                lambda: client.get_prompt("weekly_report", {}),
                lambda: client.read_resource("lab://documents/missing"),
            ]:
                try:
                    await operation()
                except MCPError:
                    checks += 1
                else:
                    raise AssertionError("Expected MCP error")
        print(
            f"PASS {label}: {checks} assertions; tools/prompts/resources/templates + errors",
            flush=True,
        )


async def verify_auth() -> None:
    endpoint = "http://127.0.0.1:5293/mcp"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as api:
        for header in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Basic ds-lab-alice"},
        ):
            response = await api.post(
                endpoint,
                headers=header,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert response.status_code == 401
            assert "WWW-Authenticate" in response.headers
    for token, name in LAB_IDENTITIES.items():
        async with Client(endpoint, auth=token, timeout=15) as client:
            assert len(await client.list_tools()) == 6
            result = await client.call_tool("who_am_i")
            assert result.structured_content["name"] == name
            assert token not in str(result)
    print(
        "PASS AUTH: missing/wrong/scheme rejected; Alice/Bob identities separated; no token echo",
        flush=True,
    )


async def verify_all() -> None:
    await verify()
    await verify_auth()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(verify_all() if arguments.verify else serve())
