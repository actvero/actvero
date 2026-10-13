import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from actvero_cli.errors import CliError


def canonical_server(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CliError("invalid_server", "平台地址格式无效") from None
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(ord(c) <= 32 for c in value)
        or "%" in parsed.netloc
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        or "%" in parsed.path
    ):
        raise CliError("invalid_server", "请输入 HTTPS 平台地址；本机可用 http://127.0.0.1:5194")
    host = parsed.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    netloc = host + (
        f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def config_dir() -> Path:
    override = os.environ.get("ACTVERO_CLI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Actvero CLI"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Actvero CLI"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "actvero"


def server_for(value: str | None) -> str:
    if value:
        return canonical_server(value)
    path = config_dir() / "config.json"
    try:
        return canonical_server(json.loads(path.read_text())["server"])
    except (OSError, ValueError, KeyError, TypeError):
        raise CliError("server_required", "请通过 --server 指定平台，或先执行 auth login") from None


def save_server(server: str) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(dir=directory, prefix=".config-")
    path = Path(raw)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"server": server}, stream)
        os.replace(path, directory / "config.json")
    finally:
        path.unlink(missing_ok=True)
