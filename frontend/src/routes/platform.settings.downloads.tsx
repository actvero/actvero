import { createFileRoute } from '@tanstack/react-router'
import { ClientDownloadsSettingsPage } from '@/features/platform/client-downloads-page'

export const Route = createFileRoute('/platform/settings/downloads')({
  component: ClientDownloadsSettingsPage,
})
