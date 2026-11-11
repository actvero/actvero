import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { WorkbenchDetail } from '@/features/workbenches/detail'

export const Route = createFileRoute(
  '/_authenticated/workbenches/$workbenchId'
)({
  component: Page,
})

// eslint-disable-next-line react-refresh/only-export-components
function Page() {
  const { workbenchId } = Route.useParams()
  return (
    <AccessGate admin>
      <WorkbenchDetail workbenchId={workbenchId} />
    </AccessGate>
  )
}
