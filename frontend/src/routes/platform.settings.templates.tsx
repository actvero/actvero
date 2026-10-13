import { createFileRoute } from '@tanstack/react-router'
import { PlatformMailTemplatesPage } from '@/features/platform/mail-templates-page'

export const Route = createFileRoute('/platform/settings/templates')({
  component: PlatformMailTemplatesPage,
})
