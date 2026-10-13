import { createFileRoute } from '@tanstack/react-router'
import { AccessKeysPage } from '@/features/access-keys/page'

export const Route = createFileRoute('/_authenticated/my-access-keys')({
  component: AccessKeysPage,
})
