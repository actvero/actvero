from dataclasses import dataclass

from app.modules.integrations.models import IntegrationApplication, IntegrationKey
from app.modules.tenants.models import Tenant


@dataclass(frozen=True)
class ApplicationActor:
    tenant: Tenant
    application: IntegrationApplication
    key: IntegrationKey
