import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { MembersPage } from '@/features/members/page'
import { memberSearch } from '@/features/members/search'

export const Route = createFileRoute('/_authenticated/users')({
  validateSearch: memberSearch,
  component: () => (
    <AccessGate admin>
      <MembersPage />
    </AccessGate>
  ),
})
