import { createFileRoute } from '@tanstack/react-router'
import { ObjectStoragePage } from '@/features/object-storage/page'

export const Route = createFileRoute('/_authenticated/system/storage')({
  component: ObjectStoragePage,
})
