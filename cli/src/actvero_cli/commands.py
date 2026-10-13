import argparse
import json
import sys
from typing import Any
from uuid import UUID

from actvero_cli import __version__
from actvero_cli.client import Client
from actvero_cli.config import server_for
from actvero_cli.errors import CliError
from actvero_cli.login import login
from actvero_cli.store import CredentialStore


def resource_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("请填写完整 UUID") from None


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="actvero", description="Actvero 多组织管理 CLI")
    root.add_argument("--version", action="version", version=__version__)
    domains = root.add_subparsers(dest="domain", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server", help="平台地址；默认使用上次成功登录的平台")
    common.add_argument("--json", action="store_true", help="输出 JSON，供 Agent 和脚本读取")
    for domain, actions in (
        ("auth", ["login", "status", "logout"]),
        ("org", ["list", "show", "permissions"]),
        ("channels", ["list", "show"]),
    ):
        group = domains.add_parser(domain)
        verbs = group.add_subparsers(dest="action", required=True)
        for action in actions:
            leaf = verbs.add_parser(action, parents=[common])
            if domain == "auth" and action == "login":
                leaf.add_argument("--reauthenticate", action="store_true", help="强制重新验证登录")
            if domain in {"org", "channels"} and action != "list" or domain == "channels":
                leaf.add_argument("--org", type=resource_id, required=True, help="目标组织 UUID")
            if action == "list" and domain != "auth":
                leaf.add_argument("--page", type=int, default=1)
            if domain == "channels":
                if action == "show":
                    leaf.add_argument("--id", type=resource_id, required=True, help="渠道 UUID")
                else:
                    leaf.add_argument("--q", default="", help="搜索渠道名称或地址")
                    leaf.add_argument(
                        "--state", choices=["current", "archived", "all"], default="current"
                    )
    return root


def execute(args: argparse.Namespace, client: Client) -> dict[str, Any]:
    if args.domain == "auth":
        if args.action == "login":
            return login(client, reauthenticate=args.reauthenticate)
        if args.action == "logout":
            client.logout()
            return {"server": client.server, "message": "已退出 CLI 登录"}
        return {"server": client.server, **client.get("/me")}
    if args.domain == "org":
        if args.action == "list":
            return client.get("/organizations", page=args.page)
        suffix = "/permissions" if args.action == "permissions" else ""
        return client.get("/organizations/" + args.org + suffix)
    path = "/organizations/" + args.org + "/channels"
    if args.action == "show":
        return client.get(path + "/" + args.id)
    return client.get(path, q=args.q, state=args.state, page=args.page)


def display(result: dict[str, Any]) -> None:
    org = result.get("organization")
    if isinstance(org, dict):
        print(f"组织：{org['name']}  [{org['org_id']}]")
    page = result.get("result", result)
    if isinstance(page, dict) and isinstance(page.get("items"), list):
        for item in page["items"]:
            identity = item.get("org_id", item.get("id", ""))
            state = (
                item.get("reason")
                or item.get("role")
                or ("已启用" if item.get("manual_enabled") else "已停用")
            )
            print(f"{identity}  {item.get('name', '')}  {state}")
        print(f"本页 {len(page['items'])} 项 / 共 {page.get('total', len(page['items']))} 项")
    else:
        # Responses use server-side public views; credentials never reach the output path.
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "page", 1) < 1:
        parser().error("--page 必须大于零")
    client = None
    try:
        server = server_for(args.server)
        client = Client(server, CredentialStore(server))
        result = execute(args, client)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            display(result)
        return 0
    except CliError as error:
        if args.json:
            print(json.dumps(error.payload(), ensure_ascii=False), file=sys.stderr)
        else:
            print(error.message, file=sys.stderr)
            if error.request_id:
                print("请求编号：" + error.request_id, file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        # No traceback containing a callback URL or credential blob.
        print("CLI 无法完成此操作，请检查本机配置和平台版本", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("操作已中断", file=sys.stderr)
        return 130
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
