import { createFileRoute } from '@tanstack/react-router'
import { ObjectStoragePage } from '@/features/object-storage/page'

export const Route = createFileRoute('/platform/settings/storage')({
  component: ObjectStoragePage,
})
