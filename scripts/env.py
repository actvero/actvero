"""Generate independent credentials without overwriting existing configuration."""
import argparse
import base64
import os
import secrets
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=root / ".env")
target = parser.parse_args().output
if target.exists():
    print(".env 已存在，保留原配置。")
else:
    content = (root / ".env.example").read_text()
    for name in ("APP_DB_PASSWORD", "KEYCLOAK_DB_PASSWORD", "POSTGRES_ADMIN_PASSWORD",
                 "KEYCLOAK_ADMIN_PASSWORD", "WEB_CLIENT_SECRET", "PROVISIONER_CLIENT_SECRET"):
        content = content.replace("__" + name + "__", secrets.token_hex(24))
    content = content.replace('__NEWAPI_MANAGEMENT_TOKEN__', 'nap_' + secrets.token_hex(32))
    content = content.replace('__NEWAPI_SESSION_SECRET__', secrets.token_hex(32))
    content = content.replace("__SESSION_ENCRYPTION_KEY__", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle: handle.write(content)
    print("已生成独立的本机凭据（.env，权限 0600）。")
