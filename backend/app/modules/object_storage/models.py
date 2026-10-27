"""Shared object storage; retain the existing table and foreign keys on upgrade."""

from uuid import UUID, uuid4

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ObjectStorage(Base):
    __tablename__ = "client_storage"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    endpoint: Mapped[str] = mapped_column(String(2048))
    region: Mapped[str] = mapped_column(String(100))
    bucket: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(200), default="actvero")
    public_url: Mapped[str] = mapped_column(String(2048))
    path_style: Mapped[bool] = mapped_column(default=False)
    credentials: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    locator_frozen: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
