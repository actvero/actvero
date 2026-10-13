"""增量配置本机 Keycloak 桌面公共客户端；默认只读，不覆盖既有 Realm。"""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=root / ".env")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    base, target = dotenv_values(root / ".env"), dotenv_values(args.env)
    origin, realm = target["ACTVERO_OIDC_ISSUER"].rstrip("/").rsplit("/realms/", 1)
    from urllib.parse import urlsplit

    if urlsplit(origin).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("此升级工具仅用于本机开发 Keycloak。")
    desired = next(
        c
        for c in json.loads(
            (root / "identity/bootstrap/actvero-realm.json").read_text()
        )["clients"]
        if c["clientId"] == "actvero-desktop"
    )
    async with httpx.AsyncClient(timeout=30) as http:
        auth = await http.post(
            origin + "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": base["KC_BOOTSTRAP_ADMIN_USERNAME"],
                "password": base["KC_BOOTSTRAP_ADMIN_PASSWORD"],
            },
        )
        auth.raise_for_status()
        headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
        url = origin + "/admin/realms/" + realm + "/clients"
        result = await http.get(
            url, params={"clientId": desired["clientId"]}, headers=headers
        )
        result.raise_for_status()
        clients = result.json()
        if clients:
            actual = clients[0]
            checks = (
                "enabled",
                "protocol",
                "publicClient",
                "standardFlowEnabled",
                "implicitFlowEnabled",
                "directAccessGrantsEnabled",
                "serviceAccountsEnabled",
                "redirectUris",
                "webOrigins",
                "fullScopeAllowed",
                "defaultClientScopes",
                "optionalClientScopes",
            )
            if (
                any(
                    (
                        set(actual.get(k) or []) != set(desired[k])
                        if isinstance(desired[k], list)
                        else actual.get(k) != desired[k]
                    )
                    for k in checks
                )
                or actual.get("attributes", {}).get("pkce.code.challenge.method")
                != "S256"
            ):
                raise SystemExit(
                    "现有桌面客户端配置有差异，未覆盖；请按 ADR 0010 核对。"
                )
            print("桌面公共客户端已正确配置；未更改现有配置。")
        elif not args.apply:
            print("需要新增 actvero-desktop 公共客户端（S256 + loopback）；尚未修改。")
        else:
            created = await http.post(url, json=desired, headers=headers)
            created.raise_for_status()
            print(
                "已新增 actvero-desktop 公共客户端；原 Realm、账号、Web 客户端均保留。"
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.HTTPError as error:
        raise SystemExit("配置失败：" + type(error).__name__) from None
