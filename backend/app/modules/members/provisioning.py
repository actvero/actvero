import secrets
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select, text

from app.modules.auth.service import DB, limit, provider
from app.modules.members.models import Invitation, MemberCreation, Membership
from app.modules.members.schemas import MemberCreate, MemberCreated
from app.modules.members.service import access, member_view, record
from app.modules.users.models import LoginIdentity, User


async def create_member(
    tenant_id: UUID, payload: MemberCreate, request: Request, db: DB
) -> MemberCreated:
    actor = await access(request, db, tenant_id)
    await limit(db, "create-member:" + str(actor.user.id), 20, 300)
    actor = await access(request, db, tenant_id, write=True)
    email = str(payload.email).casefold()
    operation = await db.get(MemberCreation, payload.request_id)
    if operation and (operation.tenant_id != tenant_id or operation.created_by != actor.user.id):
        raise HTTPException(409, "请求标识已使用，请重新打开添加表单")
    if operation is None:
        operation = await db.scalar(
            select(MemberCreation).where(
                MemberCreation.tenant_id == tenant_id, MemberCreation.email == email
            )
        )
        if operation and operation.member_id:
            raise HTTPException(409, "此邮箱已有成员，请在成员列表中管理")
    if operation and (operation.email, operation.name, operation.role) != (
        email,
        payload.name,
        payload.role,
    ):
        raise HTTPException(409, "此邮箱有未完成的创建请求，请使用原姓名和角色重试")
    if operation is None:
        pending = await db.scalar(
            select(Invitation.id).where(
                Invitation.tenant_id == tenant_id,
                Invitation.email == email,
                Invitation.status == "pending",
            )
        )
        if pending:
            raise HTTPException(409, "此邮箱已有邀请，请在邀请记录中继续处理")
        existing = await db.scalar(
            select(Membership.id)
            .join(User)
            .where(Membership.tenant_id == tenant_id, func.lower(User.email) == email)
        )
        if existing:
            raise HTTPException(409, "此邮箱已有成员，请在成员列表中管理")
        operation = MemberCreation(
            id=payload.request_id,
            tenant_id=tenant_id,
            created_by=actor.user.id,
            email=email,
            name=payload.name,
            role=payload.role,
            marker=secrets.token_hex(32),
        )
        db.add(operation)
        # Save the recovery marker, not the password, before remote creation.
        await db.commit()
        actor = await access(request, db, tenant_id, write=True)
        operation = await db.get(MemberCreation, payload.request_id, populate_existing=True)
        if operation is None:
            raise HTTPException(409, "此前创建请求已被身份服务拒绝，请检查信息后重试")
    if operation.member_id:
        member = await db.get(Membership, operation.member_id)
        assert member is not None
        user = await db.get(User, member.user_id)
        assert user is not None
        return MemberCreated(
            member=member_view(member, user, actor.user), initial_password_reused=True
        )
    try:
        subject, reused = await provider(request).create_member_user(
            email, operation.name, payload.password.get_secret_value(), operation.marker
        )
    except HTTPException as error:
        if error.status_code in {409, 422}:
            # A definite rejection created no account for this marker; permit correction
            # or invitation. Keep the marker for uncertain failures so retries are safe.
            await db.delete(operation)
            await db.commit()
        raise
    issuer = provider(request).settings.oidc_issuer
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:identity))"),
        {"identity": issuer + "|" + subject},
    )
    identity = await db.scalar(
        select(LoginIdentity).where(
            LoginIdentity.issuer == issuer, LoginIdentity.subject == subject
        )
    )
    if identity is None:
        user = User(name=operation.name, email=email)
        db.add(user)
        await db.flush()
        identity = LoginIdentity(
            user_id=user.id, issuer=issuer, subject=subject, email_verified=False
        )
        db.add(identity)
        await db.flush()
    else:
        existing_user = await db.get(User, identity.user_id)
        assert existing_user is not None
        user = existing_user
    member = await db.scalar(
        select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
    )
    if member:
        raise HTTPException(409, "此账号已有成员关系，请在成员列表中管理")
    member = Membership(tenant_id=tenant_id, user_id=user.id, role=operation.role, source="direct")
    db.add(member)
    await db.flush()
    operation.member_id = member.id
    record(
        db, actor, "member.created", member.id, user.name, {"role": member.role, "source": "direct"}
    )
    await db.commit()
    return MemberCreated(
        member=member_view(member, user, actor.user), initial_password_reused=reused
    )
