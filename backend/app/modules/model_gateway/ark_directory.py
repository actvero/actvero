"""Live public Plan text-model directory, distinct from key-scoped discovery.

Plan keys do not authorize the AK/SK control-plane ListArkAgentPlanModel API
and the Plan data plane has no /models route. Read the supplier's published
support table without sending a supplier key or maintaining a local inventory.
"""

import asyncio
import json
import re
import time

import httpx2
from fastapi import HTTPException

from app.core.config import Settings
from app.core.outbound import PinnedTransport, resolve

SOURCE = "https://docs.volcengine.com/docs/ark/agent-plan-personal-plan-overview?lang=zh"
MAX_BYTES = 3_000_000


def parse_models(document: str) -> list[str]:
    match = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", document, re.S)
    if not match:
        raise ValueError("Missing public document data")
    router = json.loads(match[1])
    page = router["loaderData"]["docs/(libid)/(docid$)/page"]["curDoc"]
    zones = json.loads(page["Content"])["data"]

    def text(zone: str) -> str:
        return (
            "".join(op["insert"] for op in zones[zone]["ops"] if isinstance(op.get("insert"), str))
            .replace("*", "")
            .strip()
        )

    for op in zones["0"]["ops"]:
        table = op.get("attributes", {}).get("aceTable")
        if not isinstance(table, str):
            continue
        row_zone, column_zone = table.split()
        rows = [item["insert"]["id"] for item in zones[row_zone]["ops"]]
        columns = [item["insert"]["id"] for item in zones[column_zone]["ops"]]
        if len(columns) < 3 or len(rows) > 500:
            continue
        if [text(f"x{rows[0]}x{column}") for column in columns[:3]] != ["分类", "领域", "模型名称"]:
            continue
        models = []
        for row in rows[1:]:
            if not text(f"x{row}x{columns[1]}").startswith("文本生成"):
                continue
            # The first line is the callable primary name. Notes and aliases in
            # parentheses are not model IDs; do not infer names from prose.
            primary = text(f"x{row}x{columns[2]}").splitlines()[0].split()[0]
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", primary):
                raise ValueError("Unrecognized public model name")
            models.append(primary)
        if models:
            return list(dict.fromkeys(models))
    raise ValueError("Missing public model support table")


async def fetch_document(settings: Settings) -> str:
    transport = PinnedTransport(
        SOURCE, lambda url: resolve(url, [], dns=settings.llm_public_dns), max_bytes=MAX_BYTES
    )
    async with asyncio.timeout(20):
        async with httpx2.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=15
        ) as http:
            async with http.stream(
                "GET", SOURCE, headers={"Accept": "text/html", "Accept-Encoding": "identity"}
            ) as response:
                if response.status_code != 200:
                    raise ValueError("Public directory unavailable")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Compressed public directory rejected")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ValueError("Public directory too large")
                    body.extend(chunk)
                return body.decode("utf-8")


class PlanDirectory:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.models: list[str] = []
        self.expires = 0.0

    async def get(self, settings: Settings) -> list[str]:
        async with self.lock:
            if self.models and time.monotonic() < self.expires:
                return list(self.models)
            try:
                models = parse_models(await fetch_document(settings))
            except (
                httpx2.HTTPError,
                HTTPException,
                TimeoutError,
                ValueError,
                OSError,
                KeyError,
                TypeError,
                AttributeError,
                IndexError,
            ) as exc:
                raise HTTPException(
                    503, "火山公开模型目录暂不可用，请稍后重试或手动填写模型 ID"
                ) from exc
            self.models = models
            self.expires = time.monotonic() + 3600
            return list(models)


directory = PlanDirectory()
