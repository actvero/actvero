import base64
import hashlib
import secrets
import socket
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from actvero_cli.client import Client
from actvero_cli.config import save_server
from actvero_cli.errors import CliError


class Loopback:
    def __init__(self) -> None:
        self.result: dict[str, str] | None = None
        self.state = ""
        self.issuer = ""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Never log callback code, state or URL.

            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                values = parse_qs(parsed.query, keep_blank_values=True)
                valid = (
                    parsed.path == "/actvero/cli/callback"
                    and len(self.path) < 8192
                    and values.get("state") == [owner.state]
                    and values.get("iss") == [owner.issuer]
                    and (bool(values.get("code")) != bool(values.get("error")))
                    and len(values.get("code", values.get("error", []))) == 1
                    and bool(values.get("code", values.get("error", [""]))[0])
                    and not owner.result
                )
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(
                    ("登录结果已收到，请返回终端。" if valid else "无效的登录回调。").encode()
                )
                if valid:
                    owner.result = {key: val[0] for key, val in values.items() if len(val) == 1}

        class Server(HTTPServer):
            def get_request(self) -> tuple[socket.socket, Any]:
                connection, address = super().get_request()
                connection.settimeout(2)
                return connection, address

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.5

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/actvero/cli/callback"

    def wait(self, timeout: float = 300) -> dict[str, str]:
        end = time.monotonic() + timeout
        while not self.result and time.monotonic() < end:
            self.server.handle_request()
        if not self.result:
            raise CliError("login_timeout", "登录等待超时，请重新发起")
        if "error" in self.result:
            raise CliError("login_cancelled", "浏览器登录未完成")
        return self.result

    def close(self) -> None:
        self.server.server_close()


def login(client: Client, *, reauthenticate: bool = False) -> dict[str, Any]:
    with client.store.lock():
        # Verify credential storage works before authorizing a new session.
        previous = client.store.load()
        if previous.get("login_pending"):
            client.public("POST", "/login/cancel", json=previous["login_pending"])
            previous = {}
            client.store.save(previous)
        if previous.get("tokens"):
            raise CliError(
                "already_logged_in", "此平台已有 CLI 登录，请先退出；更换账号不会覆盖旧会话"
            )
        client.store.save(previous)
        metadata = client.public("GET", "/metadata")
        if metadata.get("contract_version") != 1 or metadata.get("scope") != "management:read":
            raise CliError("unsupported_contract", "此平台不支持当前 CLI 管理契约")
        callback = Loopback()
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        proof = None
        completed = False
        try:
            started = client.public(
                "POST",
                "/login/start",
                json={
                    "contract_version": 1,
                    "redirect_uri": callback.redirect_uri,
                    "code_challenge": challenge,
                    "device_name": "CLI · " + socket.gethostname()[:90],
                    "reauthenticate": reauthenticate,
                },
            )
            proof = {
                "attempt_id": started["attempt_id"],
                "state": started["state"],
                "code_verifier": verifier,
            }
            client.store.save({"login_pending": proof})
            callback.state, callback.issuer = started["state"], metadata["issuer"]
            if started.get("issuer") != callback.issuer:
                raise CliError("issuer_mismatch", "登录来源与平台发现不一致")
            target, issuer = urlsplit(started["authorization_url"]), urlsplit(callback.issuer)
            if (
                (target.scheme, target.netloc) != (issuer.scheme, issuer.netloc)
                or target.scheme not in {"https", "http"}
                or target.username
                or target.password
                or (target.scheme == "http" and target.hostname not in {"127.0.0.1", "localhost"})
            ):
                raise CliError("invalid_login_url", "平台返回了不兼容的授权地址")
            if not webbrowser.open(started["authorization_url"]):
                raise CliError("browser_unavailable", "无法打开系统浏览器，请在有浏览器的本机登录")
            result = callback.wait()
            tokens = client.public(
                "POST",
                "/login/exchange",
                json={
                    **proof,
                    "issuer": callback.issuer,
                    "code": result["code"],
                },
            )
            client.save_login(tokens, str(metadata["instance_id"]))
            completed = True
            save_server(client.server)
            return {
                "server": client.server,
                "session_id": tokens["session_id"],
                "scope": tokens["scope"],
            }
        finally:
            callback.close()
            if proof and not completed:
                try:
                    client.public("POST", "/login/cancel", json=proof)
                    client.store.save({})
                except CliError:
                    # A later login must cancel this exact attempt before starting another.
                    pass
