import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { readDashboardSearch } from '@/features/llm-calls/dashboard-search'
import { LlmUsagePage } from '@/features/llm-calls/usage-page'

export const Route = createFileRoute('/_authenticated/llm-usage')({
  validateSearch: readDashboardSearch,
  component: function Page() {
    const search = Route.useSearch()
    return (
      <AccessGate admin>
        <LlmUsagePage search={search} />
      </AccessGate>
    )
  },
})
