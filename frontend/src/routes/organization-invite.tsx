import { createFileRoute } from '@tanstack/react-router'
import { OrganizationInvitationPage } from '@/features/platform/organization-invitation-page'

export const Route = createFileRoute('/organization-invite')({
  component: OrganizationInvitationPage,
})
