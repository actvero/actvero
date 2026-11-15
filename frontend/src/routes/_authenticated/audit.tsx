import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AuditPage } from '@/features/audit/page'
import { AccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/_authenticated/audit')({
  validateSearch: z.object({
    target: z.uuid().optional(),
    action: z.string().max(50).optional(),
  }).parse,
  component: function AuditRoute() {
    const { target, action } = Route.useSearch()
    return (
      <AccessGate admin>
        <AuditPage
          key={`${target ?? ''}/${action ?? ''}`}
          target={target}
          action={action}
        />
      </AccessGate>
    )
  },
})
