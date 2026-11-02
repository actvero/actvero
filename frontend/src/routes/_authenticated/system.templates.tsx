import { createFileRoute } from '@tanstack/react-router'
import { PlatformMailTemplatesPage } from '@/features/platform/mail-templates-page'

export const Route = createFileRoute('/_authenticated/system/templates')({
  component: PlatformMailTemplatesPage,
})
