import { createFileRoute } from '@tanstack/react-router'
import { PlatformGeneralSettingsPage } from '@/features/platform/settings-page'

export const Route = createFileRoute('/_authenticated/system/general')({
  component: PlatformGeneralSettingsPage,
})
