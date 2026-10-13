from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    name_managed_locally: Mapped[bool] = mapped_column(default=False, server_default="false")
    avatar_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avatar_version: Mapped[UUID | None] = mapped_column()

    @property
    def avatar_url(self) -> str | None:
        return f"/api/v1/account/avatar?v={self.avatar_version}" if self.avatar_version else None

    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginIdentity(Base):
    __tablename__ = "login_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(default=False)
