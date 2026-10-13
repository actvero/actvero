import { createFileRoute } from '@tanstack/react-router'
import { OrganizationInvitationsPage } from '@/features/platform/invitations-page'

export const Route = createFileRoute('/platform/invitations')({
  component: OrganizationInvitationsPage,
})
