"""Shared Web/CLI release domain. Only validated, immutable artifacts enter a feed."""

import math
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import yaml
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.client_distribution.models import (
    ClientArtifact,
    ClientDistribution,
    ClientJob,
    ClientStorage,
    ClientUpdateHead,
    ClientUpload,
)
from app.modules.client_distribution.schemas import ArtifactView, DistributionView, UploadView
from app.modules.client_distribution.storage import ObjectStore
from app.modules.object_storage.service import download_url, storage, store  # noqa: F401
from app.modules.platform.access import PlatformActor
from app.modules.platform.download_models import ClientRelease
from app.modules.platform.downloads import changed, event
from app.modules.platform.operations import access, locked, revision  # noqa: F401


async def release(
    db: AsyncSession, ident: UUID, expected: int | None = None
) -> tuple[ClientRelease, ClientDistribution]:
    row = await db.get(ClientRelease, ident, populate_existing=True)
    distribution = await db.get(ClientDistribution, ident, populate_existing=True)
    if not row or not distribution:
        raise HTTPException(404, "更新版本不存在")
    if expected is not None:
        revision(row.revision, expected)
    return row, distribution


def draft(row: ClientRelease) -> None:
    if row.status != "draft":
        raise HTTPException(409, "已发布文件和版本不可修改，请创建新版本")


async def artifacts(db: AsyncSession, ident: UUID) -> list[ClientArtifact]:
    return list(
        (
            await db.scalars(
                select(ClientArtifact)
                .where(ClientArtifact.release_id == ident)
                .order_by(ClientArtifact.target, ClientArtifact.role)
            )
        ).all()
    )


async def view(db: AsyncSession, ident: UUID) -> DistributionView:
    row = await db.get(ClientRelease, ident)
    if not row:
        raise HTTPException(404, "客户端版本不存在")
    distribution = await db.get(ClientDistribution, ident)
    return DistributionView(
        id=row.id,
        version=row.version,
        channel=distribution.channel if distribution else "latest",
        notes=row.notes,
        minimum_os=distribution.minimum_os if distribution else {},
        source_commit=distribution.source_commit if distribution else None,
        legacy=distribution is None,
        legacy_assets=row.assets if distribution is None else [],
        status=row.status,
        revision=row.revision,
        artifacts=[ArtifactView.model_validate(a) for a in await artifacts(db, ident)],
    )


async def upload_context(
    request: Request, db: AsyncSession, ident: UUID, *, active: bool = True
) -> tuple[ClientUpload, ClientArtifact, ClientStorage, ObjectStore]:
    who = await access(request, db, "releases.write")
    upload = await db.get(ClientUpload, ident, populate_existing=True)
    if not upload or upload.actor_id != who.user.id:
        raise HTTPException(404, "上传任务不存在")
    artifact = await db.get(ClientArtifact, upload.artifact_id, populate_existing=True)
    if not artifact:
        raise HTTPException(404, "上传文件不存在")
    if active:
        if upload.status != "uploading" or upload.expires_at <= now():
            raise HTTPException(409, "上传任务已完成、过期或取消，请回查状态")
        row, _ = await release(db, artifact.release_id)
        draft(row)
    profile = await storage(db, artifact.storage_id)
    return upload, artifact, profile, store(request, profile)


def upload_view(upload: ClientUpload, artifact: ClientArtifact) -> UploadView:
    return UploadView(
        id=upload.id,
        artifact_id=artifact.id,
        status=upload.status,
        part_size=upload.part_size,
        part_count=math.ceil((artifact.size_bytes or 0) / upload.part_size),
        size_bytes=artifact.size_bytes or 0,
        expected_sha512=artifact.expected_sha512,
        parts=upload.parts,
        expires_at=upload.expires_at,
    )


def part_size(upload: ClientUpload, artifact: ClientArtifact, number: int) -> int:
    total = artifact.size_bytes or 0
    if not 1 <= number <= math.ceil(total / upload.part_size):
        raise HTTPException(422, "分片编号超出文件范围")
    return min(upload.part_size, total - (number - 1) * upload.part_size)


async def enqueue(db: AsyncSession, artifact: ClientArtifact, actor_id: UUID) -> ClientJob:
    existing = await db.scalar(
        select(ClientJob).where(
            ClientJob.artifact_id == artifact.id, ClientJob.status.in_(["pending", "running"])
        )
    )
    if existing:
        return existing
    if artifact.published_at:
        raise HTTPException(409, "已发布文件不可重新处理")
    artifact.status, artifact.error = "verifying", None
    job = ClientJob(artifact_id=artifact.id, actor_id=actor_id)
    db.add(job)
    await db.flush()
    return job


def canonical_name(version: str, target: str, role: str) -> str:
    extension = "exe" if target.startswith("win-") else ("dmg" if role == "installer" else "zip")
    return f"actvero-{version}-{target}.{extension}" + (".blockmap" if role == "blockmap" else "")


def file_url(base: str, channel: str, version: str, target: str, role: str) -> str:
    filename = quote(canonical_name(version, target, role))
    return f"{base.rstrip('/')}/api/v1/client-artifacts/{channel}/{target}/{filename}"


def newer(new: str, old: str) -> bool:
    """SemVer precedence, including numeric versus alphanumeric prerelease identifiers."""

    def parts(value: str) -> tuple[tuple[int, ...], list[str] | None]:
        core, sep, pre = value.partition("-")
        return tuple(int(n) for n in core.split(".")), pre.split(".") if sep else None

    a, ap = parts(new)
    b, bp = parts(old)
    if a != b:
        return a > b
    if ap is None or bp is None:
        return ap is None and bp is not None
    for left, right in zip(ap, bp, strict=False):
        if left == right:
            continue
        if left.isdigit() and right.isdigit():
            return int(left) > int(right)
        if left.isdigit() != right.isdigit():
            return not left.isdigit()
        return left > right
    return len(ap) > len(bp)


async def validate_targets(
    db: AsyncSession, row: ClientRelease, dist: ClientDistribution, targets: list[str]
) -> tuple[list[ClientArtifact], dict[str, int]]:
    all_files = await artifacts(db, row.id)
    selected: list[ClientArtifact] = []
    heads: dict[str, int] = {}
    for target in dict.fromkeys(targets):
        files = {a.role: a for a in all_files if a.target == target}
        required = {"payload", "blockmap"} | ({"installer"} if target.startswith("mac-") else set())
        if not required <= files.keys() or any(files[r].status != "ready" for r in required):
            raise HTTPException(422, f"{target} 的安装包、更新包或 blockmap 尚未校验完成")
        if not dist.minimum_os.get(target):
            raise HTTPException(422, f"请填写 {target} 的最低系统版本")
        payload = files["payload"]
        if not payload.range_supported:
            raise HTTPException(422, f"{target} 下载源未通过 Range 检查，无法启用差分下载")
        if files["blockmap"].validation.get("payload_size") != payload.size_bytes:
            raise HTTPException(422, f"{target} 的 blockmap 与更新包大小不匹配")
        head = await db.get(ClientUpdateHead, (dist.channel, target), populate_existing=True)
        heads[target] = head.revision if head else 0
        if head and head.release_id:
            previous = await db.get(ClientRelease, head.release_id)
            if previous and not newer(row.version, previous.version):
                raise HTTPException(409, "通道只能向更高版本推进；修复已发布版本请使用新版本号")
        elif head:
            # Withdrawal clears the feed, but must not reset its version floor.
            history = await db.scalars(
                select(ClientRelease.version)
                .join(ClientDistribution)
                .join(ClientArtifact, ClientArtifact.release_id == ClientRelease.id)
                .where(
                    ClientDistribution.channel == dist.channel,
                    ClientArtifact.target == target,
                    ClientArtifact.role == "payload",
                    ClientArtifact.published_at.is_not(None),
                )
            )
            if any(not newer(row.version, version) for version in history):
                raise HTTPException(409, "通道只能向更高版本推进；下架不会重置已发布版本")
        selected.extend(files[r] for r in sorted(required))
    return selected, heads


def manifest(
    base: str, row: ClientRelease, dist: ClientDistribution, target: str, payload: ClientArtifact
) -> str:
    url = file_url(base, dist.channel, row.version, target, "payload")
    document: dict[str, Any] = {
        "version": row.version,
        "files": [{"url": url, "sha512": payload.sha512, "size": payload.size_bytes}],
        "path": url,
        "sha512": payload.sha512,
        "releaseDate": now().isoformat(),
        "releaseNotes": row.notes,
    }
    # minimumSystemVersion uses OS kernel versions in electron-updater; human-facing
    # minimum_os labels must never be copied into that machine-readable field.
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def record(db: AsyncSession, who: PlatformActor, row: ClientRelease, action: str) -> None:
    changed(row)
    event(db, who, row, action)


def expiry() -> datetime:
    return now() + timedelta(days=7)


__all__ = ["storage", "store", "download_url", "access", "locked", "revision"]
