import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { LlmCallsPage } from '@/features/llm-calls/page'
import { readCallSearch } from '@/features/llm-calls/search'

export const Route = createFileRoute('/_authenticated/llm-calls')({
  validateSearch: readCallSearch,
  component: function Page() {
    const search = Route.useSearch()
    return (
      <AccessGate admin>
        <LlmCallsPage search={search} />
      </AccessGate>
    )
  },
})
