import { createFileRoute } from '@tanstack/react-router'
import { ClientDistributionPage } from '@/features/client-distribution/page'

export const Route = createFileRoute('/platform/settings/downloads')({
  component: ClientDistributionPage,
})
