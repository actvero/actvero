import { createFileRoute } from '@tanstack/react-router'
import { ClientDownloadsPage } from '@/features/client-downloads/page'

export const Route = createFileRoute('/download')({
  component: ClientDownloadsPage,
})
