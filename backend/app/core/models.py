"""Explicit metadata registry shared by Alembic and the application."""

from app.modules.access_keys.models import AccessKey, AccessKeyPolicy
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import OrganizationOpeningFlow, RateLimit, WebSession
from app.modules.desktop.models import DesktopLogin, DeviceSession, DeviceToken
from app.modules.desktop_mcp.models import NativeOAuthAttempt, ResourceToken
from app.modules.experts.models import ExpertCategoryRecord, ExpertRecord, ExpertRelease
from app.modules.llm.models import (
    CatalogModel,
    ModelCall,
    ModelChannel,
    ModelImportReceipt,
    MutationReceipt,
    PointConversion,
    QuotaClock,
    RouteHealth,
    UsageSettlement,
)
from app.modules.management.models import ManagementLogin, ManagementSession, ManagementToken
from app.modules.mcp.models import (
    McpActivity,
    McpConnection,
    McpContent,
    McpHealth,
    McpOAuthAttempt,
    McpPolicy,
    McpService,
    McpSnapshot,
)
from app.modules.members.models import Invitation, MemberCreation, Membership
from app.modules.platform.download_models import (
    ClientRecommendation,
    ClientRelease,
    ClientReleaseEvent,
)
from app.modules.quota.models import QuotaPolicy
from app.modules.skills.models import (
    Skill,
    SkillCategoryRecord,
    SkillDistribution,
    SkillPackage,
    SkillVersion,
)
from app.modules.tenants.models import (
    BrandAsset,
    Installation,
    OrganizationInvitation,
    OrganizationOpening,
    PlatformOperator,
    Tenant,
)
from app.modules.users.models import LoginIdentity, User

__all__ = [
    "BrandAsset",
    "ClientRelease",
    "ClientRecommendation",
    "ClientReleaseEvent",
    "ManagementLogin",
    "ManagementSession",
    "ManagementToken",
    "ExpertCategoryRecord",
    "ExpertRecord",
    "ExpertRelease",
    "AccessKey",
    "AccessKeyPolicy",
    "UsageSettlement",
    "QuotaClock",
    "PointConversion",
    "QuotaPolicy",
    "CatalogModel",
    "RouteHealth",
    "ModelCall",
    "ModelChannel",
    "ModelImportReceipt",
    "MutationReceipt",
    "Skill",
    "SkillCategoryRecord",
    "SkillVersion",
    "SkillPackage",
    "SkillDistribution",
    "NativeOAuthAttempt",
    "ResourceToken",
    "McpActivity",
    "McpHealth",
    "McpService",
    "McpConnection",
    "McpSnapshot",
    "McpPolicy",
    "McpContent",
    "McpOAuthAttempt",
    "AuditEvent",
    "DesktopLogin",
    "DeviceSession",
    "DeviceToken",
    "RateLimit",
    "WebSession",
    "OrganizationOpeningFlow",
    "Invitation",
    "Membership",
    "MemberCreation",
    "Installation",
    "OrganizationInvitation",
    "OrganizationOpening",
    "PlatformOperator",
    "Tenant",
    "LoginIdentity",
    "User",
]
