from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict


def https_url(value: str) -> str:
    p = urlsplit(value)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.fragment
        or any(ord(c) < 33 or c in '<>"\\' for c in value)
    ):
        raise ValueError("请使用不含账号、密码和片段的 HTTPS 地址")
    _ = p.port
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
