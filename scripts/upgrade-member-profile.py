"""Add the admin-only provisioning marker to an existing local Keycloak profile.

Does not create users, modify credentials/roles or replace a realm. Existing
profile settings are read and retained. Without --apply, this is read-only.
"""
import argparse
import asyncio
from pathlib import Path

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, default=root / '.env')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    base = dotenv_values(root / '.env')
    target = dotenv_values(args.env)
    issuer = target['ACTVERO_OIDC_ISSUER'].rstrip('/')
    origin, realm = issuer.rsplit('/realms/', 1)
    if not origin.startswith(('http://127.0.0.1:', 'http://localhost:')):
        raise SystemExit('此升级工具仅用于本机开发 Keycloak。')
    async with httpx.AsyncClient(timeout=30) as client:
        auth = await client.post(origin + '/realms/master/protocol/openid-connect/token', data={
            'grant_type': 'password', 'client_id': 'admin-cli',
            'username': base['KC_BOOTSTRAP_ADMIN_USERNAME'],
            'password': base['KC_BOOTSTRAP_ADMIN_PASSWORD'],
        })
        auth.raise_for_status()
        headers = {'Authorization': 'Bearer ' + auth.json()['access_token']}
        url = origin + '/admin/realms/' + realm + '/users/profile'
        current = await client.get(url, headers=headers)
        current.raise_for_status()
        profile = current.json()
        marker = {'name': 'actvero_member', 'permissions': {'view': ['admin'], 'edit': ['admin']}}
        existing = next((a for a in profile['attributes'] if a['name'] == marker['name']), None)
        if existing:
            if existing.get('permissions') != marker['permissions']:
                raise SystemExit('现有 actvero_member 权限不符合仅管理员可见/编辑的要求，未更改。')
            print('成员创建标记已配置；未更改任何配置或账号。')
            return
        if not args.apply:
            print('需要新增 actvero_member 属性（仅管理员可见/编辑）；尚未修改。')
            return
        profile['attributes'].append(marker)
        response = await client.put(url, headers=headers, json=profile)
        response.raise_for_status()
        check = await client.get(url, headers=headers)
        check.raise_for_status()
        actual = next(a for a in check.json()['attributes'] if a['name'] == marker['name'])
        if actual.get('permissions') != marker['permissions']:
            raise SystemExit('配置验证失败。')
        print('已新增仅管理员可用的成员创建标记，原用户、角色和其他配置均保留。')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except httpx.HTTPError as error:
        raise SystemExit('身份服务配置失败：' + type(error).__name__) from None
