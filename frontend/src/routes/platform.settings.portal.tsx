import { createFileRoute } from '@tanstack/react-router'
import { PlatformPortalSettingsPage } from '@/features/platform/portal-settings-page'

export const Route = createFileRoute('/platform/settings/portal')({
  component: PlatformPortalSettingsPage,
})
