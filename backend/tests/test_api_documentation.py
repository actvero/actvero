from app.main import create_app


def test_desktop_documentation_keeps_auth_boundaries_explicit():
    schema = create_app().openapi()
    paths = schema["paths"]
    me = paths["/api/v1/desktop/me"]["get"]
    assert me["summary"] == "获取桌面本人资料"
    assert me["security"] == [{"DesktopAccess": []}]
    assert "401" in me["responses"] and "403" in me["responses"]
    assert schema["components"]["securitySchemes"]["DesktopAccess"]["scheme"] == "bearer"
    for path in ("metadata", "login/start", "login/exchange", "login/cancel", "refresh", "logout"):
        operation = next(iter(paths["/api/v1/desktop/" + path].values()))
        assert not operation.get("security")
        assert operation["description"]
    assert "description" in schema["components"]["schemas"]["DesktopTokens"]["properties"]["scope"]
    assert (
        "不是响应中的"
        in schema["components"]["schemas"]["RefreshSession"]["properties"]["request_id"][
            "description"
        ]
    )
    assert "非标准 MCP" in paths["/api/v1/mcp/services/{service_id}/run"]["post"]["description"]


def test_native_mcp_contract_describes_resource_boundaries():
    schema = create_app().openapi()
    paths = schema["paths"]
    mint = paths["/api/v1/desktop/resource-tokens"]["post"]
    assert mint["security"] == [{"DesktopAccess": []}]
    operations = [
        op
        for path, methods in paths.items()
        if path.startswith("/api/v1/desktop/mcp")
        for op in methods.values()
    ]
    assert operations and all(op["security"] == [{"McpResource": []}] for op in operations)
    assert all(op["summary"] and op["description"] for op in operations)
    gateway = paths["/api/mcp/services/{service_id}"]["post"]
    assert gateway["security"] == [{"McpResource": []}]
    assert (
        gateway["requestBody"]["content"]["application/json"]["example"]["method"] == "tools/list"
    )
    assert not any("oauth/callback" in path for path in paths)
