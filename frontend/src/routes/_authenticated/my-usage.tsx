import { createFileRoute } from '@tanstack/react-router'
import { MyUsagePage } from '@/features/usage/page'

export const Route = createFileRoute('/_authenticated/my-usage')({
  component: MyUsagePage,
})
