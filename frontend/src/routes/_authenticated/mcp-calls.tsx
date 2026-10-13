import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ActivityPage } from '@/features/mcp/activity-page'

export const Route = createFileRoute('/_authenticated/mcp-calls')({
  validateSearch: (search: Record<string, unknown>) => ({
    service: typeof search.service === 'string' ? search.service : undefined,
  }),
  component: function Page() {
    const { service } = Route.useSearch()
    return (
      <AccessGate admin>
        <ActivityPage key={service} category='call' serviceId={service} />
      </AccessGate>
    )
  },
})
