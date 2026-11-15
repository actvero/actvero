import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { IntegrationsPage } from '@/features/integrations/page'

export const Route = createFileRoute('/_authenticated/integrations')({
  validateSearch: z.object({ app: z.uuid().optional().catch(undefined) }),
  component: function IntegrationsRoute() {
    const { app } = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
      <AccessGate admin>
        <IntegrationsPage
          appId={app}
          openApplication={(id) => void navigate({ search: { app: id } })}
        />
      </AccessGate>
    )
  },
})
