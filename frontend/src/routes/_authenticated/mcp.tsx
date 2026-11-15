import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { McpRoutePage } from '@/features/mcp/route-page'

export const Route = createFileRoute('/_authenticated/mcp')({
  validateSearch: z.object({ service: z.uuid().optional() }).parse,
  component: function McpRoute() {
    const { service } = Route.useSearch()
    return (
      <AccessGate>
        <McpRoutePage serviceId={service} />
      </AccessGate>
    )
  },
})
