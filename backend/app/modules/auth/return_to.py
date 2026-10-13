"""Login destinations are relative page URLs, never API actions or external URLs."""

import re

from fastapi import HTTPException


def login_return_to(value: str) -> str:
    path = re.split(r"[?#]", value, maxsplit=1)[0]
    if (
        len(value) > 2048
        or any(ord(character) <= 32 or ord(character) == 127 for character in value)
        or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]*", path)
        or re.match(r"/(?:api|login)(?:/|$)", path)
    ):
        raise HTTPException(400, "登录返回地址无效")
    return "/console" if path == "/" else value
