"""Metadata-only evidence for one upstream execution attempt.

The owner passes this object explicitly across SDK and response boundaries.  A
dispatch callback proves only that the validated local transport was invoked;
it cannot prove that the provider accepted or billed the request.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4

EVIDENCE_VERSION = 1
_METRICS = {
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "cache_read_tokens": "tokens",
    "cache_write_5m_tokens": "tokens",
    "cache_write_1h_tokens": "tokens",
    "search_units": "searches",
    "input_characters": "characters",
    "image_count": "images",
    "audio_duration_ms": "seconds",
    "raw_prompt_tokens": "tokens",
    "raw_completion_tokens": "tokens",
    "raw_input_tokens": "tokens",
    "raw_output_tokens": "tokens",
    "raw_prompt_token_count": "tokens",
    "raw_candidates_token_count": "tokens",
    "raw_thoughts_token_count": "tokens",
}
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class AttemptTrace:
    def __init__(self, attempt_id: str | None = None) -> None:
        if attempt_id is not None and not _SAFE_ID.fullmatch(attempt_id):
            raise ValueError("Invalid attempt id")
        self.attempt_id = attempt_id or str(uuid4())
        self._started = time.monotonic()
        self._finished_at: float | None = None
        self.sent: bool | None = None
        self.output_started = False
        self.first_output_ms: int | None = None
        self.upstream_terminal = False
        self.client_terminal: bool | None = None
        self.upstream_status: int | None = None
        self.retry_after_seconds: int | None = None
        self.error_code: str | None = None
        self.error_scope: str | None = None
        self.retryable_hint: bool | None = None
        self._explicit_uncertain = False
        self._cancelled = False
        self._usage: dict[tuple[str, str], dict[str, Any]] = {}

    def mark_sent(self) -> None:
        self.sent = True

    def mark_not_sent(self) -> None:
        if self.sent is None:
            self.sent = False

    def mark_output(self) -> None:
        if not self.output_started:
            self.output_started = True
            self.first_output_ms = max(0, round((time.monotonic() - self._started) * 1000))

    def mark_upstream_terminal(self) -> None:
        self.upstream_terminal = True

    def mark_client_terminal(self) -> None:
        self.client_terminal = True

    def note_upstream_status(self, status: int) -> None:
        if type(status) is int and 100 <= status <= 599:
            self.upstream_status = status
            if status != 429:
                self.retry_after_seconds = None

    def note_retry_after_seconds(self, seconds: int | None) -> None:
        """Retain only a verified 429 delay, without copying response headers."""
        self.retry_after_seconds = (
            seconds
            if self.upstream_status == 429 and type(seconds) is int and 0 <= seconds <= 2**53 - 1
            else None
        )

    def observe_usage(self, usage: dict[str, Any], *, phase: str = "terminal") -> None:
        """Keep only bounded numeric meter fields; never retain provider payloads."""
        if not isinstance(usage, dict):
            return
        phase = (
            phase
            if phase in {"partial", "terminal", "validated_input", "confirmed_delivery"}
            else "partial"
        )
        for field, metric in _METRICS.items():
            if field not in usage:
                continue
            raw = usage[field]
            value = raw if type(raw) is int and 0 <= raw <= 10**12 else None
            if field == "input_characters" or (
                field == "audio_duration_ms" and phase == "validated_input"
            ):
                source = "validated_input"
            elif field == "image_count":
                source = "confirmed_delivery"
            else:
                source = "upstream" if usage.get("source") == "upstream" else "unknown"
            entry = {
                "field": field,
                "value": value,
                "metric": metric,
                "source": source,
                "complete": value is not None
                and source != "unknown"
                and phase in {"terminal", "confirmed_delivery", "validated_input"},
                "phase": phase,
                "attempt_id": self.attempt_id,
                "evidence_version": EVIDENCE_VERSION,
            }
            previous = self._usage.get((field, phase))
            if previous is None or (
                (entry["value"] is not None or previous["value"] is None)
                and (entry["source"] != "unknown" or previous["source"] == "unknown")
            ):
                self._usage[field, phase] = entry

    def note_error(self, error: BaseException) -> None:
        """Classify structured failure fields without copying messages or URLs."""
        code = getattr(error, "code", None)
        safe_code = (
            code if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else "unexpected_error"
        )
        if self.error_code is None or self.error_code == "unexpected_error":
            self.error_code = safe_code
        status = getattr(error, "upstream_status", None)
        if status is not None:
            self.note_upstream_status(status)
        retryable = getattr(error, "retryable", None)
        if type(retryable) is bool:
            self.retryable_hint = retryable
        self._explicit_uncertain |= getattr(error, "uncertain", False) is True
        if self.sent is False:
            self.error_scope = "preflight"
        elif safe_code in {"image_delivery_failed", "audio_delivery_failed"}:
            self.error_scope = "delivery"
        elif safe_code in {"sdk_response_error", "unsupported_sdk_parameters"}:
            self.error_scope = "sdk"
        elif self.upstream_status is not None:
            self.error_scope = "upstream"
        elif self.sent is True:
            self.error_scope = (
                "transport" if safe_code in {"upstream_unavailable", "upstream_timeout"} else "sdk"
            )
        else:
            self.error_scope = "unknown"

    def snapshot(self) -> dict[str, Any]:
        elapsed = (self._finished_at or time.monotonic()) - self._started
        uncertain = (
            self._explicit_uncertain
            or self._cancelled
            or (self.sent is None or (self.sent is True and not self.upstream_terminal))
        )
        if self.sent is False:
            uncertain = False
        return {
            "attempt_id": self.attempt_id,
            "evidence_version": EVIDENCE_VERSION,
            "sent": self.sent,
            "output_started": self.output_started,
            "first_output_ms": self.first_output_ms,
            "upstream_terminal": self.upstream_terminal,
            "client_terminal": self.client_terminal,
            "upstream_status": self.upstream_status,
            "retry_after_seconds": self.retry_after_seconds,
            "error_code": self.error_code,
            "error_scope": self.error_scope,
            "retryable_hint": self.retryable_hint,
            "uncertain": uncertain,
            "certainly_unused": self.sent is False,
            "duration_ms": max(0, round(elapsed * 1000)),
            "usage_evidence": list(self._usage.values()),
        }

    def finish(self, error: BaseException | None = None, cancelled: bool = False) -> dict[str, Any]:
        if error is not None:
            self.note_error(error)
        if cancelled:
            self._cancelled = True
            if self.error_code in {None, "unexpected_error"}:
                self.error_code = "caller_cancelled"
                self.error_scope = "client"
        self._finished_at = time.monotonic()
        return self.snapshot()
