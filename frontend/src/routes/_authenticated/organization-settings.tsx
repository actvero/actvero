import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { OrganizationSettingsPage } from '@/features/organization/settings-page'

export const Route = createFileRoute('/_authenticated/organization-settings')({
  component: () => (
    <AccessGate admin>
      <OrganizationSettingsPage />
    </AccessGate>
  ),
})
