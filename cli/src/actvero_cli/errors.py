class CliError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 0, request_id: str = ""):
        super().__init__(message)
        self.code, self.message = code, message
        self.status, self.request_id = status, request_id

    def payload(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
                "request_id": self.request_id,
            }
        }
