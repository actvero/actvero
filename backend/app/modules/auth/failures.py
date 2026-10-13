"""Safe identity failure classification: transport/configuration errors do not log users out."""

from email.utils import parsedate_to_datetime

import httpx
import httpx2
from fastapi import HTTPException


class IdentityUnavailable(HTTPException):
    code = "identity_unavailable"

    def __init__(self, error: httpx.HTTPError | httpx2.HTTPError | None = None) -> None:
        status = 503
        headers = None
        if (
            isinstance(error, (httpx.HTTPStatusError, httpx2.HTTPStatusError))
            and error.response.status_code == 429
        ):
            status = 429
            retry = error.response.headers.get("Retry-After", "")
            if retry and len(retry) <= 100 and retry.isascii():
                try:
                    if not retry.isdigit():
                        parsedate_to_datetime(retry)
                    headers = {"Retry-After": retry}
                except (ValueError, TypeError, OverflowError):
                    pass
        super().__init__(status, "身份服务暂不可用，请稍后重试；登录凭据已保留", headers=headers)
