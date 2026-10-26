from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from starlette.responses import RedirectResponse, Response

from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, now
from app.modules.client_distribution.models import ClientDistribution
from app.modules.platform.access import PlatformActor, platform_access
from app.modules.platform.download_models import (
    ClientRecommendation,
    ClientRelease,
    ClientReleaseEvent,
)
from app.modules.platform.download_schemas import (
    Architecture,
    ClientAsset,
    Platform,
    PublicDownloads,
    PublicRelease,
    RecommendationSave,
    RecommendationView,
    ReleaseEventView,
    ReleasePage,
    ReleasePublish,
    ReleaseRevision,
    ReleaseSave,
    ReleaseStatus,
    ReleaseView,
)
from app.modules.tenants.models import Installation

router = APIRouter(prefix="/api/v1/platform/downloads", tags=["client-downloads"])


async def locked_actor(request: Request, db: DB) -> PlatformActor:
    await platform_access(request, db)
    # Serializes unique versions and recommendations across all deployment operators.
    if await db.scalar(select(Installation).where(Installation.id == 1).with_for_update()) is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    return await platform_access(request, db)


async def release(db: DB, release_id: UUID, revision: int | None = None) -> ClientRelease:
    row = await db.get(ClientRelease, release_id, populate_existing=True)
    if row is None:
        raise HTTPException(404, "客户端版本不存在")
    if revision is not None and row.revision != revision:
        raise HTTPException(409, "版本已被其他操作修改，请读取最新记录后核对")
    if revision is not None and (await db.get(ClientDistribution, release_id)) is not None:
        raise HTTPException(409, "此版本由更新发布管理维护，请使用更新发布入口")
    return row


def event(db: DB, actor: PlatformActor, row: ClientRelease, action: str) -> None:
    db.add(
        ClientReleaseEvent(
            actor_id=actor.user.id,
            actor_name=actor.user.name,
            release_id=row.id,
            version=row.version,
            action=action,
            revision=row.revision,
        )
    )


def changed(row: ClientRelease) -> None:
    row.revision += 1
    row.updated_at = now()


async def recommendations(db: DB) -> list[RecommendationView]:
    rows = (
        await db.scalars(
            select(ClientRecommendation).order_by(
                ClientRecommendation.platform, ClientRecommendation.architecture
            )
        )
    ).all()
    return [RecommendationView.model_validate(row) for row in rows]


async def recommend(db: DB, row: ClientRelease, platform: str, architecture: str) -> None:
    if row.status != "published" or not any(
        a["platform"] == platform and a["architecture"] == architecture for a in row.assets
    ):
        raise HTTPException(409, "只能推荐已发布版本中实际提供的安装包")
    existing = await db.get(ClientRecommendation, (platform, architecture))
    if existing:
        existing.release_id = row.id
    else:
        db.add(
            ClientRecommendation(platform=platform, architecture=architecture, release_id=row.id)
        )


@router.get("/public", response_model=PublicDownloads)
async def public_downloads(db: DB, response: Response) -> PublicDownloads:
    response.headers["Cache-Control"] = "no-store"
    rows = (
        await db.scalars(
            select(ClientRelease)
            .where(ClientRelease.status == "published")
            .order_by(ClientRelease.release_date.desc(), ClientRelease.created_at.desc())
        )
    ).all()
    ids = {row.id for row in rows}
    return PublicDownloads(
        items=[
            PublicRelease(
                id=row.id,
                version=row.version,
                release_date=row.release_date,
                notes=row.notes,
                assets=[ClientAsset.model_validate(a) for a in row.assets],
            )
            for row in rows
        ],
        recommendations=[r for r in await recommendations(db) if r.release_id in ids],
    )


@router.get("/{release_id}/file", status_code=307, response_class=RedirectResponse)
async def download_file(
    release_id: UUID, platform: Platform, architecture: Architecture, db: DB
) -> RedirectResponse:
    # Recheck publication at click time, including links in a stale public page.
    row = await release(db, release_id)
    asset = next(
        (
            a
            for a in row.assets
            if (a["platform"] == platform and a["architecture"] == architecture)
        ),
        None,
    )
    if row.status != "published" or asset is None:
        raise HTTPException(404, "该安装包暂未发布或已下架")
    url = ClientAsset.model_validate(asset).url
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})


@router.get("", response_model=ReleasePage)
async def list_releases(
    request: Request,
    response: Response,
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    q: Annotated[str, Query(max_length=50)] = "",
    status: ReleaseStatus | None = None,
) -> ReleasePage:
    await platform_access(request, db)
    response.headers["Cache-Control"] = "no-store"
    query = select(ClientRelease)
    if q:
        query = query.where(ClientRelease.version.contains(q.strip(), autoescape=True))
    if status:
        query = query.where(ClientRelease.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(
            query.order_by(ClientRelease.created_at.desc(), ClientRelease.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return ReleasePage(
        items=[ReleaseView.model_validate(row) for row in rows],
        total=total,
        recommendations=await recommendations(db),
    )


@router.get("/{release_id}", response_model=ReleaseView)
async def get_release(
    release_id: UUID, request: Request, response: Response, db: DB
) -> ReleaseView:
    await platform_access(request, db)
    response.headers["Cache-Control"] = "no-store"
    return ReleaseView.model_validate(await release(db, release_id))


@router.get("/{release_id}/events", response_model=list[ReleaseEventView])
async def release_events(
    release_id: UUID, request: Request, response: Response, db: DB
) -> list[ReleaseEventView]:
    await platform_access(request, db)
    response.headers["Cache-Control"] = "no-store"
    rows = (
        await db.scalars(
            select(ClientReleaseEvent)
            .where(ClientReleaseEvent.release_id == release_id)
            .order_by(ClientReleaseEvent.created_at.desc())
            .limit(30)
        )
    ).all()
    return [ReleaseEventView.model_validate(row) for row in rows]


@router.put("/{release_id}", response_model=ReleaseView)
async def save_release(
    release_id: UUID, payload: ReleaseSave, request: Request, db: DB, _: Mutation
) -> ReleaseView:
    actor = await locked_actor(request, db)
    row = await db.get(ClientRelease, release_id)
    if await db.get(ClientDistribution, release_id):
        raise HTTPException(409, "此版本由更新发布管理维护，请使用更新发布入口")
    if row is None and payload.expected_revision != 0:
        raise HTTPException(404, "客户端版本不存在")
    if row and row.revision != payload.expected_revision:
        raise HTTPException(409, "版本已修改，请读取最新记录后核对；重复创建不会新增版本")
    duplicate = await db.scalar(
        select(ClientRelease.id).where(
            ClientRelease.version == payload.version, ClientRelease.id != release_id
        )
    )
    if duplicate:
        raise HTTPException(409, "版本号已存在，请使用新的版本号")
    assets = [a.model_dump(mode="json") for a in payload.assets]
    if row is None:
        row = ClientRelease(
            id=release_id,
            version=payload.version,
            release_date=payload.release_date,
            notes=payload.notes,
            assets=assets,
            status="draft",
            revision=1,
        )
        db.add(row)
        action = "created"
    else:
        if row.status != "draft" and (
            row.version != payload.version
            or row.release_date != payload.release_date
            or row.assets != assets
        ):
            raise HTTPException(409, "已发布或下架的安装包不可替换，请新建版本")
        row.version = payload.version
        row.release_date = payload.release_date
        row.notes = payload.notes
        row.assets = assets
        changed(row)
        action = "saved"
    event(db, actor, row, action)
    await db.commit()
    return ReleaseView.model_validate(row)


@router.post("/{release_id}/publish", response_model=ReleaseView)
async def publish_release(
    release_id: UUID, payload: ReleasePublish, request: Request, db: DB, _: Mutation
) -> ReleaseView:
    actor = await locked_actor(request, db)
    row = await release(db, release_id, payload.expected_revision)
    if row.status == "published":
        raise HTTPException(409, "该版本已经发布，请读取最新记录")
    if not row.assets:
        raise HTTPException(422, "请至少添加一个安装包")
    for raw in row.assets:
        asset = ClientAsset.model_validate(raw)
        extensions = (
            (".exe", ".msi", ".zip") if asset.platform == "windows" else (".dmg", ".pkg", ".zip")
        )
        if not asset.url or not asset.minimum_os or not asset.filename.lower().endswith(extensions):
            raise HTTPException(422, "发布前请填写 HTTPS 下载链接、对应系统文件名及最低系统要求")
    row.status = "published"
    changed(row)
    if payload.recommend:
        for raw_asset in row.assets:
            await recommend(db, row, str(raw_asset["platform"]), str(raw_asset["architecture"]))
    event(db, actor, row, "published")
    await db.commit()
    return ReleaseView.model_validate(row)


@router.post("/{release_id}/withdraw", response_model=ReleaseView)
async def withdraw_release(
    release_id: UUID, payload: ReleaseRevision, request: Request, db: DB, _: Mutation
) -> ReleaseView:
    actor = await locked_actor(request, db)
    row = await release(db, release_id, payload.expected_revision)
    if row.status != "published":
        raise HTTPException(409, "只能下架已发布版本")
    row.status = "withdrawn"
    changed(row)
    await db.execute(delete(ClientRecommendation).where(ClientRecommendation.release_id == row.id))
    event(db, actor, row, "withdrawn")
    await db.commit()
    return ReleaseView.model_validate(row)


@router.post("/{release_id}/recommend", response_model=ReleaseView)
async def recommend_release(
    release_id: UUID, payload: RecommendationSave, request: Request, db: DB, _: Mutation
) -> ReleaseView:
    actor = await locked_actor(request, db)
    row = await release(db, release_id, payload.expected_revision)
    await recommend(db, row, payload.platform, payload.architecture)
    changed(row)
    event(db, actor, row, "recommended")
    await db.commit()
    return ReleaseView.model_validate(row)


@router.delete("/{release_id}", response_model=Message)
async def delete_release(
    release_id: UUID, payload: ReleaseRevision, request: Request, db: DB, _: Mutation
) -> Message:
    actor = await locked_actor(request, db)
    row = await release(db, release_id, payload.expected_revision)
    if row.status != "draft":
        raise HTTPException(409, "只有草稿可以删除，已发布版本请下架")
    event(db, actor, row, "deleted")
    await db.delete(row)
    await db.commit()
    return Message(message="草稿已删除")
