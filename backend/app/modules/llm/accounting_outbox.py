"""Durable metadata-only handoff; database outages do not interrupt SDK output.

Dispatch intents and final evidence are fsynced in the persistent app volume.
Only completed events are replayed while a request is active. Expired intents
become unknown executions after a crash; no model request is ever replayed.
"""

import asyncio
import json
import logging
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.database import Database
from app.modules.llm import settlement
from app.modules.llm.models import ModelCall
from app.modules.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Outbox:
    def __init__(self, directory: Path, database: Database) -> None:
        self.directory, self.database = directory, database
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()

    def write(self, record: dict[str, Any]) -> None:
        call_id = str(UUID(record["call_id"]))
        target = self.directory / (call_id + ".json")
        temporary = self.directory / (call_id + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(record, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    async def checkpoint(self, record: dict[str, Any], *, required: bool = False) -> None:
        try:
            # A small metadata record only; no text, messages, tools, credentials,
            # images or audio are ever part of this schema.
            await asyncio.to_thread(self.write, deepcopy(record))
            self.wake.set()
        except OSError:
            logger.error("LLM accounting outbox write failed; existing reservation remains held")
            if required:
                raise

    async def flush_one(self, path: Path) -> None:
        async with self.lock:
            try:
                record = json.loads(await asyncio.to_thread(path.read_text))
            except FileNotFoundError:
                return
            if not record["complete"]:
                if record["expires_at"] > time.time():
                    return
                record.update(
                    status="unknown",
                    error_code="execution_interrupted",
                    termination_code="execution_interrupted",
                    delivered=False,
                )
                for attempt in record["attempts"]:
                    if attempt["status"] == "pending":
                        attempt.update(
                            status="unknown", uncertain=True, error_code="execution_interrupted"
                        )
            async with self.database.sessions() as db:
                await db.scalar(
                    select(Tenant.id)
                    .where(Tenant.id == UUID(record["tenant_id"]))
                    .with_for_update()
                )
                row = await db.get(ModelCall, UUID(record["call_id"]), with_for_update=True)
                if row is None:
                    # An admission commit failed: no dispatch was authorized.
                    path.unlink(missing_ok=True)
                    return
                if row.tenant_id != UUID(record["tenant_id"]):
                    raise ValueError("Outbox tenant mismatch")
                if row.status == "pending":
                    row.attempts = record["attempts"]
                    row.status = record["status"]
                    row.error_code = record.get("error_code")
                    row.termination_code = record.get("termination_code")
                    row.duration_ms = record.get("duration_ms")
                    row.usage = record.get("usage", {})
                    row.estimates = record.get("estimates", {})
                    if row.attempts:
                        last = row.attempts[-1]
                        row.channel_id = UUID(last["channel_id"])
                        row.prices = last["prices"]
                    await settlement.complete(
                        db,
                        row.id,
                        row.usage,
                        delivered=record["delivered"],
                        certainly_unused=record.get("no_send", False) and record["complete"],
                    )
                await db.commit()
            path.unlink(missing_ok=True)

    async def flush(self, call_id: UUID) -> None:
        try:
            # Fast normal-case visibility for the usage UI. Bounded independently
            # of provider execution; the journal is the durable retry source.
            async with asyncio.timeout(0.25):
                await self.flush_one(self.directory / (str(call_id) + ".json"))
        except Exception:
            self.wake.set()
            logger.warning("LLM accounting persistence deferred")

    async def run(self) -> None:
        while True:
            self.wake.clear()
            for path in self.directory.glob("*.json"):
                try:
                    async with asyncio.timeout(5):
                        await self.flush_one(path)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("LLM accounting outbox replay deferred")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=5)
            except TimeoutError:
                pass
