from typing import NoReturn

from fastapi import HTTPException


class DesktopError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        self.code = code
        super().__init__(status_code=status, detail=message)


def fail(status: int, code: str, message: str) -> NoReturn:
    raise DesktopError(status, code, message)
