"""Session lifetimes are server policy, independent of short OIDC access tokens."""

from datetime import datetime, timedelta

from app.core.config import Settings
from app.modules.auth.models import WebSession


def deadline(session: WebSession, settings: Settings) -> datetime:
    end = session.expires_at
    if session.absolute_expires_at is not None:
        end = min(end, session.absolute_expires_at)
    # A deployment tightened to strict cannot leave older persistent sessions active.
    if settings.web_session_policy == "strict" and session.authenticated_at is not None:
        end = min(end, session.authenticated_at + timedelta(hours=settings.session_hours))
    if (
        session.policy_mode == "persistent"
        and settings.web_reauthentication_days is not None
        and session.authenticated_at is not None
    ):
        end = min(
            end, session.authenticated_at + timedelta(days=settings.web_reauthentication_days)
        )
    return end


def initialize(session: WebSession, settings: Settings, stamp: datetime) -> None:
    session.policy_mode = settings.web_session_policy
    session.renewed_at = stamp
    if settings.web_session_policy == "strict":
        session.expires_at = stamp + timedelta(hours=settings.session_hours)
        session.absolute_expires_at = session.expires_at
    else:
        session.absolute_expires_at = (
            stamp + timedelta(days=settings.web_reauthentication_days)
            if settings.web_reauthentication_days is not None
            else None
        )
        session.expires_at = stamp + timedelta(days=settings.web_recovery_days)
        if session.absolute_expires_at is not None:
            session.expires_at = min(session.expires_at, session.absolute_expires_at)


def renew(session: WebSession, settings: Settings, stamp: datetime) -> None:
    # An expired session is rejected before reaching here. Never upgrade legacy strict sessions.
    if session.policy_mode != "persistent" or settings.web_session_policy != "persistent":
        return
    if session.renewed_at is not None and stamp - session.renewed_at < timedelta(minutes=5):
        return
    end = stamp + timedelta(days=settings.web_recovery_days)
    if session.absolute_expires_at is not None:
        end = min(end, session.absolute_expires_at)
    # Tightening a cap takes effect without requiring a new authentication.
    if settings.web_reauthentication_days is not None and session.authenticated_at is not None:
        end = min(
            end, session.authenticated_at + timedelta(days=settings.web_reauthentication_days)
        )
    session.expires_at = end
    session.renewed_at = stamp
