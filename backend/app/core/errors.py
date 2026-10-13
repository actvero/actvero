from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ReferencedResourceConflict(HTTPException):
    """Explicit, safe reference metadata; arbitrary exception details stay private."""

    def __init__(self, message: str, references: list[dict[str, str]]) -> None:
        super().__init__(status_code=409, detail=message)
        self.references = references


class AcceptedRequestConflict(HTTPException):
    """A member-scoped receipt, supplied only after current authorization checks."""

    def __init__(
        self, code: str, message: str, *, call_id: str, call_status: str, settlement_status: str
    ) -> None:
        super().__init__(status_code=409, detail=message)
        self.code = code
        self.receipt = {
            "call_id": call_id,
            "call_status": call_status,
            "settlement_status": settlement_status,
        }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": getattr(error, "code", f"http_{error.status_code}"),
                    "message": str(error.detail),
                    "request_id": getattr(_request.state, "request_id", ""),
                    **(
                        {"references": error.references}
                        if isinstance(error, ReferencedResourceConflict)
                        else {}
                    ),
                    **(error.receipt if isinstance(error, AcceptedRequestConflict) else {}),
                }
            },
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        # Request values may contain credentials. Never echo them into the response.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "unsupported_contract"
                    if any("contract_version" in e["loc"] for e in _error.errors())
                    else "validation_error",
                    "message": "请求参数不符合接口要求",
                    "request_id": getattr(_request.state, "request_id", ""),
                }
            },
        )
