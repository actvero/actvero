import { createFileRoute } from '@tanstack/react-router'
import { PlatformCliSettingsPage } from '@/features/platform/cli-settings-page'

export const Route = createFileRoute('/_authenticated/system/cli')({
  component: PlatformCliSettingsPage,
})
