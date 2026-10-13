"""Observe upstream meters/termination, independently of SDK estimates and conversion."""

import json
from collections.abc import Callable
from typing import Any

from app.modules.llm.providers import chat
from app.modules.llm.providers.retrieval import UpstreamFailure, count


class Meter:
    def __init__(
        self,
        adapter: str,
        on_observation: Callable[[dict[str, Any], bool], None] | None = None,
    ) -> None:
        self.adapter = adapter
        self.raw: dict[str, Any] = {}
        self.finished = False
        self.pending = b""
        self.data: list[bytes] = []
        self.size = 0
        self.on_observation = on_observation
        # Metering is an audit aid.  It must never become a second, mandatory
        # provider protocol parser: LiteLLM owns that contract.
        self.observation_error: str | None = None

    def disable_observation(self, exc: Exception) -> None:
        """Stop best-effort raw-stream inspection without affecting LiteLLM."""
        if self.observation_error is None:
            self.observation_error = type(exc).__name__
        self.pending = b""
        self.data = []
        self.size = 0

    def observe(self, raw: dict[str, Any], *, stream: bool) -> None:
        if "error" in raw or raw.get("type") == "error":
            raise UpstreamFailure(502, "upstream_stream_error", "上游报告执行失败", uncertain=True)
        if self.adapter == "anthropic":
            if not stream:
                self.raw = raw.get("usage") or {}
                self.finished = raw.get("stop_reason") is not None
            elif raw.get("type") == "message_start":
                self.raw = dict(raw.get("message", {}).get("usage") or {})
                # message_start's output count is partial, never the final billable count.
                self.raw.pop("output_tokens", None)
            elif raw.get("type") == "message_delta":
                self.raw.update(raw.get("usage") or {})
            elif raw.get("type") == "message_stop":
                self.finished = True
        elif self.adapter == "gemini":
            if "usageMetadata" in raw:
                self.raw = raw["usageMetadata"] or {}
            if any(c.get("finishReason") for c in raw.get("candidates", [])):
                self.finished = True
        else:
            if "usage" in raw:
                self.raw = raw["usage"] or {}
            if not stream:
                self.finished = any(c.get("finish_reason") for c in raw.get("choices", []))
        self._notify()

    def _notify(self) -> None:
        if self.on_observation is None:
            return
        # Normalization may reject incomplete/ambiguous provider meters. Keep
        # the original raw signal in self.raw, but do not turn absent counts into
        # zero-valued evidence.
        normalized = self.usage()
        evidence: dict[str, Any] = {"source": "upstream"}
        raw = self.raw if isinstance(self.raw, dict) else {}
        raw_fields = (
            {"prompt_tokens": "raw_prompt_tokens", "completion_tokens": "raw_completion_tokens"}
            if self.adapter == "openai"
            else {"input_tokens": "raw_input_tokens", "output_tokens": "raw_output_tokens"}
            if self.adapter == "anthropic"
            else {
                "promptTokenCount": "raw_prompt_token_count",
                "candidatesTokenCount": "raw_candidates_token_count",
                "thoughtsTokenCount": "raw_thoughts_token_count",
            }
        )
        evidence.update(
            (safe, raw[original]) for original, safe in raw_fields.items() if original in raw
        )
        if normalized.get("source") == "upstream":
            evidence.update(
                (key, normalized[key])
                for key in ("input_tokens", "output_tokens")
                if key in normalized
            )
            if self.adapter == "openai":
                details = raw.get("prompt_tokens_details") or {}
                details = details if isinstance(details, dict) else {}
                explicit = {
                    "cache_read_tokens": "prompt_cache_hit_tokens" in raw
                    or "cached_tokens" in details,
                    "cache_write_5m_tokens": "cache_creation_5m_input_tokens" in raw,
                    "cache_write_1h_tokens": "cache_creation_1h_input_tokens" in raw,
                }
            elif self.adapter == "anthropic":
                writes = raw.get("cache_creation") or {}
                writes = writes if isinstance(writes, dict) else {}
                explicit = {
                    "cache_read_tokens": "cache_read_input_tokens" in raw,
                    "cache_write_5m_tokens": "ephemeral_5m_input_tokens" in writes,
                    "cache_write_1h_tokens": "ephemeral_1h_input_tokens" in writes,
                }
            else:
                explicit = {"cache_read_tokens": "cachedContentTokenCount" in raw}
            evidence.update((key, normalized[key]) for key, present in explicit.items() if present)
        self.on_observation(evidence, self.finished)

    def feed(self, chunk: bytes) -> None:
        if self.observation_error is not None:
            return
        self.pending += chunk
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            line = line.rstrip(b"\r")
            self.size += len(line)
            if self.size > 1_000_000:
                raise ValueError("SSE event too large")
            if not line:
                self.dispatch()
            elif line.startswith(b"data:"):
                self.data.append(line[5:].lstrip(b" "))
        if len(self.pending) + self.size > 1_000_000:
            raise ValueError("SSE event too large")

    def dispatch(self) -> None:
        data = b"\n".join(self.data)
        self.data, self.size = [], 0
        if not data:
            return
        if data == b"[DONE]":
            if self.adapter == "openai":
                self.finished = True
                self._notify()
            return
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("Invalid SSE object")
        self.observe(value, stream=True)

    def usage(self) -> dict[str, Any]:
        raw = self.raw
        if not isinstance(raw, dict):
            return {"source": "unknown"}
        if self.adapter == "openai":
            return chat.usage(raw)
        if self.adapter == "anthropic":
            inp, out = count(raw.get("input_tokens")), count(raw.get("output_tokens"))
            read = count(raw.get("cache_read_input_tokens", 0))
            writes = raw.get("cache_creation") or {}
            if not isinstance(writes, dict):
                return {"source": "unknown"}
            short = count(writes.get("ephemeral_5m_input_tokens", 0))
            long = count(writes.get("ephemeral_1h_input_tokens", 0))
            total = count(raw.get("cache_creation_input_tokens", 0))
            if None in (inp, out, read, short, long, total):
                return {"source": "unknown"}
            if total != short + long:  # type: ignore[operator]
                # Do not guess a cache TTL when the upstream hasn't supplied it.
                return {"source": "unknown"}
        else:
            prompt = count(raw.get("promptTokenCount"))
            candidates = count(raw.get("candidatesTokenCount"))
            thoughts = count(raw.get("thoughtsTokenCount", 0))
            read = count(raw.get("cachedContentTokenCount", 0))
            if prompt is None or candidates is None or thoughts is None or read is None:
                return {"source": "unknown"}
            if read > prompt:
                return {"source": "unknown"}
            inp, out, short, long = prompt - read, candidates + thoughts, 0, 0
        return {
            "source": "upstream",
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_tokens": read,
            "cache_write_5m_tokens": short,
            "cache_write_1h_tokens": long,
        }

    def openai_usage(self) -> dict[str, Any] | None:
        meter = self.usage()
        public = chat.public_usage(meter)
        if public is not None:
            public.update(
                cache_creation_5m_input_tokens=meter["cache_write_5m_tokens"],
                cache_creation_1h_input_tokens=meter["cache_write_1h_tokens"],
            )
        return public
