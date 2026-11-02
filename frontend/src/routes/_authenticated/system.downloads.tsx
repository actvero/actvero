import { createFileRoute } from '@tanstack/react-router'
import { ClientDistributionPage } from '@/features/client-distribution/page'

export const Route = createFileRoute('/_authenticated/system/downloads')({
  component: ClientDistributionPage,
})
