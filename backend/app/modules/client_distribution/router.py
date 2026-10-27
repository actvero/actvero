"""One management contract, exposed with independent Web and CLI authentication."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select, update
from starlette.responses import RedirectResponse, Response

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, now, provider
from app.modules.client_distribution import service as domain
from app.modules.client_distribution.models import (
    ClientArtifact,
    ClientDistribution,
    ClientJob,
    ClientPublicationPlan,
    ClientStorage,
    ClientUpdateHead,
    ClientUpload,
)
from app.modules.client_distribution.schemas import (
    SEMVER,
    TARGETS,
    ArtifactCreate,
    ArtifactView,
    DistributionSave,
    DistributionView,
    HeadView,
    JobView,
    PartAck,
    PartsSign,
    PlanCreate,
    PlanView,
    Publish,
    Revision,
    UploadView,
)
from app.modules.object_storage.router import router as storage_router
from app.modules.platform.download_models import ClientRecommendation, ClientRelease
from app.modules.platform.downloads import event, recommend

router = APIRouter(tags=["client-distribution"])
public_router = APIRouter(tags=["client-updates"])


router.include_router(storage_router, prefix="/storage")


@router.get("/releases", response_model=dict[str, list[DistributionView]])
async def list_releases(
    request: Request, db: DB, version: str | None = None
) -> dict[str, list[DistributionView]]:
    await domain.access(request, db)
    ids = (
        await db.scalars(
            select(ClientRelease.id).order_by(ClientRelease.created_at.desc()).limit(100)
        )
    ).all()
    return {"items": [await domain.view(db, ident) for ident in ids]}


@router.get("/releases/{ident}", response_model=DistributionView)
async def get_release(ident: UUID, request: Request, db: DB) -> DistributionView:
    await domain.access(request, db)
    return await domain.view(db, ident)


@router.put("/releases/{ident}", response_model=DistributionView)
async def save_release(
    ident: UUID, payload: DistributionSave, request: Request, db: DB
) -> DistributionView:
    who = await domain.locked(request, db, "releases.write")
    row = await db.get(ClientRelease, ident)
    dist = await db.get(ClientDistribution, ident)
    if row and not dist and row.status != "draft":
        raise HTTPException(409, "历史已发布版本保留下载记录，请创建新版本")
    if (
        dist
        and payload.source_commit
        and dist.source_commit
        and payload.source_commit != dist.source_commit
    ):
        raise HTTPException(409, "同一版本的构建必须来自同一源码提交")
    if (
        row
        and dist
        and payload.expected_revision == 0
        and row.version == payload.version
        and row.notes == payload.notes
        and dist.channel == payload.channel
        and dist.updates_enabled == payload.updates_enabled
        and dist.minimum_os == payload.minimum_os
        and (not payload.source_commit or dist.source_commit == payload.source_commit)
    ):
        return await domain.view(db, ident)
    domain.revision(row.revision if row else 0, payload.expected_revision)
    if await db.scalar(
        select(ClientRelease.id).where(
            ClientRelease.version == payload.version, ClientRelease.id != ident
        )
    ):
        raise HTTPException(409, "版本号已经存在")
    if row:
        domain.draft(row)
        if dist and (row.version != payload.version or dist.channel != payload.channel):
            raise HTTPException(409, "更新版本号和通道创建后不可修改，请创建新版本")
        if not dist:
            row.version = payload.version
        row.notes = payload.notes
        domain.record(db, who, row, "saved")
    else:
        row = ClientRelease(
            id=ident,
            version=payload.version,
            release_date=now().date(),
            notes=payload.notes,
            assets=[],
            status="draft",
            revision=1,
        )
        db.add(row)
        await db.flush()
        event(db, who, row, "created")
    if not dist:
        dist = ClientDistribution(release_id=ident, channel=payload.channel)
        db.add(dist)
    if payload.source_commit:
        dist.source_commit = payload.source_commit
    dist.updates_enabled = payload.updates_enabled
    dist.minimum_os = {str(k): v for k, v in payload.minimum_os.items()}
    await db.commit()
    return await domain.view(db, ident)


@router.put("/releases/{ident}/artifacts/{artifact_id}", response_model=ArtifactView)
async def add_artifact(
    ident: UUID, artifact_id: UUID, payload: ArtifactCreate, request: Request, db: DB
) -> ArtifactView:
    who = await domain.locked(request, db, "releases.write")
    existing = await db.get(ClientArtifact, artifact_id)
    if existing:
        source_url = (
            provider(request).unseal(existing.source_url_ciphertext).get("url")
            if existing.source_url_ciphertext
            else existing.url
            if existing.source == "url"
            else None
        )
        if (
            existing.release_id != ident
            or existing.target != payload.target
            or existing.role != payload.role
            or existing.filename != payload.filename
            or existing.expected_sha512 != payload.sha512
            or (payload.size_bytes is not None and existing.size_bytes != payload.size_bytes)
            or existing.storage_id
            != (
                (payload.storage_id or existing.storage_id)
                if not payload.url or payload.mirror
                else None
            )
            or source_url != payload.url
            or (existing.source == "mirror") != payload.mirror
        ):
            raise HTTPException(409, "文件操作编号已被使用")
        return ArtifactView.model_validate(existing)
    row, _ = await domain.release(db, ident, payload.expected_revision)
    domain.draft(row)
    if await db.scalar(
        select(ClientArtifact.id).where(
            ClientArtifact.release_id == ident,
            ClientArtifact.target == payload.target,
            ClientArtifact.role == payload.role,
        )
    ):
        raise HTTPException(409, "此目标和用途已有文件，请先删除草稿中的旧文件")
    managed = not payload.url or payload.mirror
    profile = await domain.storage(db, payload.storage_id) if managed else None
    if profile:
        profile.locator_frozen = True
    # Recreating a deleted draft ID must never reuse an orphaned completed object.
    key = (
        f"{profile.prefix}/clients/{row.version}/{payload.target}/{uuid4().hex}/{payload.filename}"
        if profile
        else None
    )
    artifact = ClientArtifact(
        id=artifact_id,
        release_id=ident,
        target=payload.target,
        role=payload.role,
        filename=payload.filename,
        source="mirror" if payload.mirror else "upload" if managed else "url",
        storage_id=profile.id if profile else None,
        object_key=key,
        source_url_ciphertext=provider(request).seal({"url": payload.url})
        if payload.mirror
        else None,
        url=(f"{profile.public_url}/{key}" if profile.public_url else None)
        if profile
        else payload.url,
        size_bytes=payload.size_bytes,
        expected_sha512=payload.sha512,
        status="pending",
        validation={},
    )
    db.add(artifact)
    await db.flush()
    if not payload.url:
        db.add(
            ClientUpload(
                id=artifact_id,
                artifact_id=artifact_id,
                actor_id=who.user.id,
                status="pending",
                expires_at=domain.expiry(),
            )
        )
    else:
        await domain.enqueue(db, artifact, who.user.id)
    domain.record(db, who, row, "artifact_added")
    await db.commit()
    return ArtifactView.model_validate(artifact)


@router.delete("/artifacts/{ident}", response_model=Message)
async def delete_artifact(ident: UUID, payload: Revision, request: Request, db: DB) -> Message:
    who = await domain.locked(request, db, "releases.write")
    artifact = await db.get(ClientArtifact, ident)
    if not artifact:
        raise HTTPException(404, "文件不存在")
    row, _ = await domain.release(db, artifact.release_id, payload.expected_revision)
    domain.draft(row)
    upload = await db.get(ClientUpload, ident)
    if upload and upload.status not in {"pending", "aborted", "completed"}:
        raise HTTPException(409, "请先取消上传任务")
    if await db.scalar(
        select(ClientJob.id).where(
            ClientJob.artifact_id == ident, ClientJob.status.in_(["pending", "running"])
        )
    ):
        raise HTTPException(409, "文件仍在处理，请等待任务结束")
    await db.execute(delete(ClientJob).where(ClientJob.artifact_id == ident))
    if upload:
        await db.delete(upload)
        await db.flush()
    await db.delete(artifact)
    domain.record(db, who, row, "artifact_removed")
    await db.commit()
    return Message(message="草稿文件已移除；存储中的对象由存储保留策略清理")


@router.get("/uploads/{ident}", response_model=UploadView)
async def get_upload(ident: UUID, request: Request, db: DB) -> UploadView:
    upload, artifact, _, _ = await domain.upload_context(request, db, ident, active=False)
    return domain.upload_view(upload, artifact)


@router.post("/uploads/{ident}/start", response_model=UploadView)
async def start_upload(ident: UUID, request: Request, db: DB) -> UploadView:
    await domain.locked(request, db, "releases.write")
    upload, artifact, _, store = await domain.upload_context(request, db, ident, active=False)
    if upload.status == "completed":
        return domain.upload_view(upload, artifact)
    row, _ = await domain.release(db, artifact.release_id)
    domain.draft(row)
    if upload.status in {"uploading", "completing"}:
        return domain.upload_view(upload, artifact)
    if upload.status != "pending" and not (
        upload.status == "starting" and upload.expires_at <= now()
    ):
        raise HTTPException(409, "上传正在启动或已取消，请回查状态")
    upload.status, upload.expires_at = "starting", now() + timedelta(minutes=2)
    key = artifact.object_key or ""
    await db.commit()
    try:
        remote_id = await store.start(key)
    except HTTPException:
        # A lost provider response may leave an orphan multipart upload; bucket lifecycle
        # must abort incomplete uploads. Never replace a completed object.
        await domain.locked(request, db, "releases.write")
        await db.refresh(upload)
        upload.status = "pending"
        await db.commit()
        raise
    await domain.locked(request, db, "releases.write")
    await db.refresh(upload)
    upload.upload_id, upload.status, upload.expires_at = remote_id, "uploading", domain.expiry()
    await db.commit()
    return domain.upload_view(upload, artifact)


@router.post("/uploads/{ident}/sign", response_model=dict[int, str])
async def sign_parts(ident: UUID, payload: PartsSign, request: Request, db: DB) -> dict[int, str]:
    upload, artifact, _, store = await domain.upload_context(request, db, ident)
    sizes = {n: domain.part_size(upload, artifact, n) for n in payload.parts}
    await db.commit()
    return {
        n: await store.sign(artifact.object_key or "", upload.upload_id or "", n, size)
        for n, size in sizes.items()
    }


@router.put(
    "/uploads/{ident}/parts/{number}",
    response_model=PartAck,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def proxy_part(ident: UUID, number: int, request: Request, db: DB) -> PartAck:
    upload, artifact, _, store = await domain.upload_context(request, db, ident)
    size = domain.part_size(upload, artifact, number)
    await db.commit()
    body = bytearray()
    async with asyncio.timeout(180):
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > size:
                raise HTTPException(413, "分片超过预定大小")
    if len(body) != size:
        raise HTTPException(422, "分片大小不匹配")
    result = await store.call(
        "upload_part",
        Key=artifact.object_key,
        UploadId=upload.upload_id,
        PartNumber=number,
        Body=bytes(body),
        ContentLength=size,
    )
    return PartAck(number=number, etag=result["ETag"])


@router.post("/uploads/{ident}/ack", response_model=UploadView)
async def acknowledge(ident: UUID, payload: PartAck, request: Request, db: DB) -> UploadView:
    await domain.locked(request, db, "releases.write")
    upload, artifact, _, _ = await domain.upload_context(request, db, ident)
    domain.part_size(upload, artifact, payload.number)
    upload.parts = {**upload.parts, str(payload.number): payload.etag}
    await db.commit()
    return domain.upload_view(upload, artifact)


@router.post("/uploads/{ident}/complete", response_model=UploadView)
async def complete_upload(ident: UUID, request: Request, db: DB) -> UploadView:
    who = await domain.locked(request, db, "releases.write")
    upload, artifact, _, store = await domain.upload_context(request, db, ident, active=False)
    if upload.status == "completed":
        return domain.upload_view(upload, artifact)
    row, _ = await domain.release(db, artifact.release_id)
    domain.draft(row)
    if upload.status not in {"uploading", "completing"} or upload.expires_at <= now():
        raise HTTPException(409, "此上传任务不能完成")
    upload.status = "completing"
    await db.commit()
    key = artifact.object_key or ""
    try:
        head = await store.head(key)
        if not head:
            remote = await store.parts(key, upload.upload_id or "")
            count = domain.upload_view(upload, artifact).part_count
            if set(remote) != set(range(1, count + 1)) or any(
                remote[n][1] != domain.part_size(upload, artifact, n) for n in remote
            ):
                raise HTTPException(422, "远端分片不完整或大小不符，请继续上传")
            if any(upload.parts.get(str(n)) != remote[n][0] for n in remote):
                raise HTTPException(409, "远端分片摘要与已确认分片不同，请重新确认上传")
            await store.complete(key, upload.upload_id or "", upload.parts)
            head = await store.head(key)
        if not head or head.get("ContentLength") != artifact.size_bytes:
            raise HTTPException(422, "合并对象大小不匹配")
    except HTTPException as exc:
        if exc.status_code < 500:
            await domain.locked(request, db, "releases.write")
            await db.refresh(upload)
            upload.status = "uploading"
            await db.commit()
        raise
    await domain.locked(request, db, "releases.write")
    upload, artifact, _, _ = await domain.upload_context(request, db, ident, active=False)
    upload.status = "completed"
    await domain.enqueue(db, artifact, who.user.id)
    await db.commit()
    return domain.upload_view(upload, artifact)


@router.post("/uploads/{ident}/abort", response_model=UploadView)
async def abort_upload(ident: UUID, request: Request, db: DB) -> UploadView:
    await domain.locked(request, db, "releases.write")
    upload, artifact, _, store = await domain.upload_context(request, db, ident, active=False)
    if upload.status == "aborted":
        return domain.upload_view(upload, artifact)
    if upload.status not in {"pending", "uploading", "aborting"}:
        raise HTTPException(409, "当前任务不能取消，请先回查完成状态")
    upload.status = "aborting"
    await db.commit()
    if upload.upload_id:
        await store.abort(artifact.object_key or "", upload.upload_id)
    await domain.locked(request, db, "releases.write")
    await db.refresh(upload)
    upload.status = "aborted"
    await db.commit()
    return domain.upload_view(upload, artifact)


@router.get("/jobs", response_model=dict[str, list[JobView]])
async def list_jobs(
    request: Request, db: DB, artifact_id: UUID | None = None
) -> dict[str, list[JobView]]:
    await domain.access(request, db)
    query = select(ClientJob).order_by(ClientJob.created_at.desc()).limit(100)
    if artifact_id:
        query = query.where(ClientJob.artifact_id == artifact_id)
    return {"items": [JobView.model_validate(j) for j in (await db.scalars(query)).all()]}


@router.post("/artifacts/{ident}/verify", response_model=JobView)
async def verify_artifact(ident: UUID, request: Request, db: DB) -> JobView:
    who = await domain.locked(request, db, "releases.write")
    artifact = await db.get(ClientArtifact, ident)
    if not artifact:
        raise HTTPException(404, "文件不存在")
    row, _ = await domain.release(db, artifact.release_id)
    domain.draft(row)
    upload = await db.get(ClientUpload, ident)
    if upload and upload.status != "completed":
        raise HTTPException(409, "请先完成上传")
    job = await domain.enqueue(db, artifact, who.user.id)
    await db.commit()
    return JobView.model_validate(job)


@router.get("/heads", response_model=dict[str, list[HeadView]])
async def list_heads(request: Request, db: DB) -> dict[str, list[HeadView]]:
    await domain.access(request, db)
    return {
        "items": [
            HeadView.model_validate(h) for h in (await db.scalars(select(ClientUpdateHead))).all()
        ]
    }


@router.post("/releases/{ident}/plan", response_model=PlanView)
async def plan_release(ident: UUID, payload: PlanCreate, request: Request, db: DB) -> PlanView:
    who = await domain.locked(request, db, "releases.publish")
    row, dist = await domain.release(db, ident, payload.expected_revision)
    if row.status == "withdrawn":
        raise HTTPException(409, "已下架版本不能重新推送，请发布修复版本")
    files, heads = await domain.validate_targets(db, row, dist, list(payload.targets))
    plan = ClientPublicationPlan(
        release_id=ident,
        actor_id=who.user.id,
        release_revision=row.revision,
        heads=heads,
        artifact_ids=sorted(str(a.id) for a in files),
        expires_at=now() + timedelta(minutes=15),
    )
    db.add(plan)
    await db.commit()
    return PlanView(
        id=plan.id,
        release_id=ident,
        release_revision=row.revision,
        targets=heads,
        expires_at=plan.expires_at,
    )


@router.post("/releases/{ident}/publish", response_model=DistributionView)
async def publish_release(
    ident: UUID, payload: Publish, request: Request, db: DB
) -> DistributionView:
    who = await domain.locked(request, db, "releases.publish")
    plan = await db.get(ClientPublicationPlan, payload.plan_id, populate_existing=True)
    if not plan or plan.release_id != ident or plan.actor_id != who.user.id:
        raise HTTPException(404, "发布计划不存在")
    if plan.consumed:
        return await domain.view(db, ident)
    if plan.expires_at <= now():
        raise HTTPException(409, "发布计划已过期，请重新检查")
    row, dist = await domain.release(db, ident, plan.release_revision)
    files, heads = await domain.validate_targets(db, row, dist, list(plan.heads))
    if heads != plan.heads or sorted(str(a.id) for a in files) != plan.artifact_ids:
        raise HTTPException(409, "通道或文件已改变，请重新生成发布计划")
    base = provider(request).settings.app_url
    row.status = "published"
    assets = {(str(a["platform"]), str(a["architecture"])): a for a in row.assets}
    for target in heads:
        if dist.updates_enabled:
            payload_file = next(a for a in files if a.target == target and a.role == "payload")
            content = domain.manifest(base, row, dist, target, payload_file)
            head = await db.get(ClientUpdateHead, (dist.channel, target))
            if head:
                head.release_id, head.manifest, head.revision = ident, content, head.revision + 1
            else:
                db.add(
                    ClientUpdateHead(
                        channel=dist.channel, target=target, release_id=ident, manifest=content
                    )
                )
        role = "payload" if target.startswith("win-") else "installer"
        installer = next(a for a in files if a.target == target and a.role == role)
        platform, arch = ("windows" if target.startswith("win-") else "macos"), target.split("-")[1]
        assets[platform, arch] = {
            "platform": platform,
            "architecture": arch,
            "url": domain.file_url(base, dist.channel, row.version, target, role),
            "filename": installer.filename,
            "minimum_os": dist.minimum_os.get(target, ""),
            "size_bytes": installer.size_bytes,
            "sha256": installer.sha256,
        }
    row.assets = list(assets.values())
    for artifact in files:
        artifact.published_at = artifact.published_at or now()
    if dist.channel == "latest":
        for asset in row.assets:
            await recommend(db, row, str(asset["platform"]), str(asset["architecture"]))
    plan.consumed = True
    domain.record(db, who, row, "published")
    await db.commit()
    return await domain.view(db, ident)


@router.post("/releases/{ident}/withdraw", response_model=DistributionView)
async def withdraw_release(
    ident: UUID, payload: Revision, request: Request, db: DB
) -> DistributionView:
    who = await domain.locked(request, db, "releases.publish")
    row = await db.get(ClientRelease, ident)
    if not row:
        raise HTTPException(404, "客户端版本不存在")
    domain.revision(row.revision, payload.expected_revision)
    if row.status != "published":
        raise HTTPException(409, "只能下架已发布版本")
    row.status = "withdrawn"
    await db.execute(
        update(ClientUpdateHead)
        .where(ClientUpdateHead.release_id == ident)
        .values(release_id=None, manifest="", revision=ClientUpdateHead.revision + 1)
    )
    await db.execute(delete(ClientRecommendation).where(ClientRecommendation.release_id == ident))
    domain.record(db, who, row, "withdrawn")
    await db.commit()
    return await domain.view(db, ident)


@public_router.get("/api/v1/client-updates/actvero/{target}/{feed}")
async def update_feed(target: str, feed: str, db: DB) -> Response:
    if target not in set(TARGETS):
        raise HTTPException(404, "更新目标不存在")
    suffix = "-mac.yml" if target.startswith("mac-") else ".yml"
    channel = feed.removesuffix(suffix)
    if channel not in {"latest", "nightly"} or feed != channel + suffix:
        raise HTTPException(404, "更新通道不存在")
    head = await db.get(ClientUpdateHead, (channel, target))
    if not head or not head.release_id:
        raise HTTPException(404, "此通道尚无可用更新")
    return Response(
        head.manifest, media_type="application/yaml", headers={"Cache-Control": "no-store"}
    )


@public_router.get("/api/v1/client-artifacts/{channel}/{target}/{filename}", status_code=307)
async def artifact_redirect(
    channel: str, target: str, filename: str, request: Request, db: DB
) -> RedirectResponse:
    # Version-bearing canonical URLs are stable across storage changes. Old blockmaps
    # remain available after withdrawal because newer clients may need them for a delta.
    if channel not in {"latest", "nightly"} or target not in TARGETS:
        raise HTTPException(404, "发布文件不存在")
    roles = ["payload", "blockmap"] + (["installer"] if target.startswith("mac-") else [])
    for role in roles:
        suffix = domain.canonical_name("", target, role).removeprefix("actvero-")
        if not filename.startswith("actvero-") or not filename.endswith(suffix):
            continue
        version = filename[len("actvero-") : -len(suffix)]
        if not SEMVER.fullmatch(version):
            continue
        artifact = await db.scalar(
            select(ClientArtifact)
            .join(ClientRelease)
            .join(ClientDistribution, ClientDistribution.release_id == ClientRelease.id)
            .where(
                ClientRelease.version == version,
                ClientDistribution.channel == channel,
                ClientArtifact.target == target,
                ClientArtifact.role == role,
                ClientArtifact.published_at.is_not(None),
            )
        )
        if artifact and (artifact.url or artifact.object_key):
            url = artifact.url
            if artifact.storage_id and artifact.object_key:
                profile = await db.get(ClientStorage, artifact.storage_id)
                if not profile:
                    raise HTTPException(503, "文件存储配置不可用")
                url = await domain.download_url(request, profile, artifact.object_key)
            assert url
            return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})
    raise HTTPException(404, "发布文件不存在")
