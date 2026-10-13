import { createFileRoute } from '@tanstack/react-router'
import { OrganizationsPage } from '@/features/platform/organizations-page'

export const Route = createFileRoute('/platform/organizations')({
  component: OrganizationsPage,
})
