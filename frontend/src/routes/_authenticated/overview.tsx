import { createFileRoute } from '@tanstack/react-router'
import { OverviewPage } from '@/features/overview/page'

export const Route = createFileRoute('/_authenticated/overview')({
  component: OverviewPage,
})
