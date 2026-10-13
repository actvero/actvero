import { createFileRoute } from '@tanstack/react-router'
import { PlatformGeneralSettingsPage } from '@/features/platform/settings-page'

export const Route = createFileRoute('/platform/settings/general')({
  component: PlatformGeneralSettingsPage,
})
