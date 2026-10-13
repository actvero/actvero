import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import keyring
from filelock import FileLock, Timeout

from actvero_cli.config import config_dir
from actvero_cli.errors import CliError


class CredentialStore:
    """Single credential blob includes the durable refresh journal."""

    def __init__(self, server: str):
        self.account = hashlib.sha256(server.encode()).hexdigest()
        # Only system-backed stores are allowed. No plaintext/Null fallback.
        backend = keyring.get_keyring()
        candidates = list(getattr(backend, "backends", [backend]))
        allowed = {
            "keyring.backends.macOS",
            "keyring.backends.Windows",
            "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        }
        candidates = [b for b in candidates if type(b).__module__ in allowed]
        if not candidates:
            raise CliError(
                "secure_store_unavailable", "没有可用的系统凭据库，请配置钥匙串或 Secret Service"
            )
        self.backend = candidates[0]

    @contextmanager
    def lock(self) -> Iterator[None]:
        directory = config_dir() / "locks"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with FileLock(directory / (self.account + ".lock"), timeout=15):
                yield
        except Timeout:
            raise CliError("session_busy", "另一条 CLI 命令正在更新登录，请稍后重试") from None

    def load(self) -> dict[str, Any]:
        try:
            raw = self.backend.get_password("actvero-cli", self.account)
            result = json.loads(raw) if raw else {}
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except Exception:
            raise CliError(
                "secure_store_unavailable", "无法读取系统凭据库；未发送业务请求"
            ) from None

    def save(self, value: dict[str, Any]) -> None:
        raw = json.dumps(value, separators=(",", ":"))
        try:
            self.backend.set_password("actvero-cli", self.account, raw)
            # Backends that silently decline writes cannot acknowledge a server rotation.
            if self.backend.get_password("actvero-cli", self.account) != raw:
                raise ValueError()
        except Exception:
            raise CliError(
                "secure_store_unavailable", "登录凭据未确认保存，请保持原登录并重试"
            ) from None

    def clear(self) -> None:
        try:
            if self.backend.get_password("actvero-cli", self.account) is not None:
                self.backend.delete_password("actvero-cli", self.account)
        except Exception:
            raise CliError("secure_store_unavailable", "无法清除本机登录凭据") from None
