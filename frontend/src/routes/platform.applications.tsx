import { createFileRoute } from '@tanstack/react-router'
import { ApplicationsPage } from '@/features/platform/applications-page'

export const Route = createFileRoute('/platform/applications')({
  component: ApplicationsPage,
})
