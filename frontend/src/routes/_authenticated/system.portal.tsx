import { createFileRoute } from '@tanstack/react-router'
import { PlatformPortalSettingsPage } from '@/features/platform/portal-settings-page'

export const Route = createFileRoute('/_authenticated/system/portal')({
  component: PlatformPortalSettingsPage,
})
