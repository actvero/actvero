import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { KnowledgePage } from '@/features/knowledge/page'

const search = z.object({
  base: z.uuid().optional(),
  view: z.enum(['create', 'defaults']).optional(),
})
export const Route = createFileRoute('/_authenticated/knowledge')({
  validateSearch: search.parse,
  component: function KnowledgeRoute() {
    const state = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
      <AccessGate>
        <KnowledgePage
          baseId={state.base}
          view={state.view}
          onOpen={(value) => void navigate({ search: value })}
        />
      </AccessGate>
    )
  },
})
