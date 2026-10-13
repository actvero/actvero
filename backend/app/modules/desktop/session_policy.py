"""Device recovery is independent of browser SSO and short resource authority."""

from datetime import datetime, timedelta

from app.core.config import Settings
from app.modules.desktop.models import DeviceSession


def deadline(session: DeviceSession, settings: Settings) -> datetime:
    end = min(session.expires_at, session.idle_expires_at)
    if session.absolute_expires_at is not None:
        end = min(end, session.absolute_expires_at)
    if settings.desktop_session_policy == "strict":
        end = min(end, session.created_at + timedelta(hours=settings.desktop_session_hours))
    if session.policy_mode == "persistent" and settings.desktop_reauthentication_days is not None:
        end = min(end, session.created_at + timedelta(days=settings.desktop_reauthentication_days))
    return end


def initialize(session: DeviceSession, settings: Settings, stamp: datetime) -> None:
    session.policy_mode = settings.desktop_session_policy
    if settings.desktop_session_policy == "persistent":
        session.absolute_expires_at = (
            stamp + timedelta(days=settings.desktop_reauthentication_days)
            if settings.desktop_reauthentication_days is not None
            else None
        )
        renew(session, settings, stamp)
    else:
        session.absolute_expires_at = session.expires_at


def renew(session: DeviceSession, settings: Settings, stamp: datetime) -> None:
    if session.policy_mode != "persistent" or settings.desktop_session_policy != "persistent":
        return
    end = stamp + timedelta(days=settings.desktop_recovery_days)
    if session.absolute_expires_at is not None:
        end = min(end, session.absolute_expires_at)
    if settings.desktop_reauthentication_days is not None:
        end = min(end, session.created_at + timedelta(days=settings.desktop_reauthentication_days))
    session.expires_at = session.idle_expires_at = end
