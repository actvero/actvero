"""Grant the explicitly approved provisioner permission for realm SMTP synchronization.

Local SaaS only. Read-only unless --apply; preserves users, credentials and other roles.
"""

import argparse
import asyncio
from pathlib import Path

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--env-file", type=Path, default=root / ".env")
    args = parser.parse_args()
    env = dotenv_values(args.env_file)
    issuer = env["ACTVERO_OIDC_ISSUER"].rstrip("/")
    origin, realm = issuer.rsplit("/realms/", 1)
    if env.get("ACTVERO_PLATFORM_EDITION") != "saas" or not origin.startswith(
        ("http://127.0.0.1:", "http://localhost:")
    ):
        raise SystemExit("Only the local SaaS instance is supported")
    async with httpx.AsyncClient(timeout=20) as client:
        auth = await client.post(
            origin + "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": env["KC_BOOTSTRAP_ADMIN_USERNAME"],
                "password": env["KC_BOOTSTRAP_ADMIN_PASSWORD"],
            },
        )
        auth.raise_for_status()
        headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
        base = origin + "/admin/realms/" + realm

        async def get(path, **kwargs):
            result = await client.get(base + path, headers=headers, **kwargs)
            result.raise_for_status()
            return result.json()

        provisioners = await get(
            "/clients",
            params={
                "clientId": env.get(
                    "ACTVERO_PROVISIONER_CLIENT_ID", "actvero-provisioner"
                )
            },
        )
        if len(provisioners) != 1 or not provisioners[0].get("serviceAccountsEnabled"):
            raise SystemExit("Provisioner service account unavailable")
        service = await get(
            "/clients/" + provisioners[0]["id"] + "/service-account-user"
        )
        management = await get("/clients", params={"clientId": "realm-management"})
        role = await get("/clients/" + management[0]["id"] + "/roles/manage-realm")
        path = (
            "/users/" + service["id"] + "/role-mappings/clients/" + management[0]["id"]
        )
        roles = await get(path)
        if any(value["id"] == role["id"] for value in roles):
            print("Provisioner already has manage-realm; no role changes")
        elif not args.apply:
            print(
                "Provisioner requires manage-realm for SMTP synchronization; no changes"
            )
        else:
            result = await client.post(base + path, headers=headers, json=[role])
            result.raise_for_status()
            assert any(value["id"] == role["id"] for value in await get(path))
            print("Granted manage-realm to the provisioner service account only")

        # Fixed same-origin pages plus the dedicated UUID-only verification callback namespace.
        # No origin-wide wildcard and no manage-clients grant to the application.
        web_clients = await get(
            "/clients",
            params={"clientId": env.get("ACTVERO_WEB_CLIENT_ID", "actvero-web")},
        )
        if len(web_clients) != 1:
            raise SystemExit("Web client unavailable")
        web_client = web_clients[0]
        redirects = web_client.get("redirectUris", [])
        expected = [
            env["ACTVERO_APP_URL"].rstrip("/") + path
            for path in (
                "/organization-invite",
                "/organization-onboarding",
                "/api/v1/organization-onboarding/verified/*",
            )
        ]
        missing = [value for value in expected if value not in redirects]
        if missing and args.apply:
            result = await client.put(
                base + "/clients/" + web_client["id"],
                headers=headers,
                json={"redirectUris": [*redirects, *missing]},
            )
            result.raise_for_status()
            saved = await get("/clients/" + web_client["id"])
            assert all(value in saved["redirectUris"] for value in expected)
            print("Registered same-origin organization-opening return pages")
        elif missing:
            print("Organization-opening return pages need registration; no changes")
        else:
            print("Organization-opening return pages already registered")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.HTTPError as error:
        raise SystemExit(
            "Identity permission update failed: " + type(error).__name__
        ) from None
