import { createFileRoute } from '@tanstack/react-router'
import { PlatformMailPage } from '@/features/platform/mail-page'

export const Route = createFileRoute('/platform/settings/mail')({
  component: PlatformMailPage,
})
