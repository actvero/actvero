"""Independent waits for response progress and a visible overall execution budget."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ExecutionTimeout(TimeoutError):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


class Timeouts:
    def __init__(self, total: float, first_response: float, idle: float) -> None:
        started = time.monotonic()
        self.deadline = started + total
        self.first_deadline = started + first_response
        self.total, self.first_response, self.idle = total, first_response, idle

    def remaining(self) -> float:
        return max(0.001, self.deadline - time.monotonic())

    @asynccontextmanager
    async def waiting(self, *, first: bool) -> AsyncIterator[None]:
        phase_deadline = self.first_deadline if first else time.monotonic() + self.idle
        deadline = min(self.deadline, phase_deadline)
        timer = asyncio.timeout_at(deadline)
        try:
            async with timer:
                yield
        except TimeoutError:
            if not timer.expired():
                raise
            if self.deadline <= phase_deadline:
                code = "upstream_timeout"
                message = f"已达到模型配置的总时长上限（{self.total:g} 秒）"
            elif first:
                code = "upstream_first_response_timeout"
                message = f"等待模型首个响应超过 {self.first_response:g} 秒"
            else:
                code = "upstream_idle_timeout"
                message = f"模型连续 {self.idle:g} 秒未返回新的输出"
            raise ExecutionTimeout(code, message) from None
