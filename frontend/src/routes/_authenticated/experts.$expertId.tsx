import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ExpertEditor } from '@/features/experts/editor'

export const Route = createFileRoute('/_authenticated/experts/$expertId')({
  component: Page,
})
// eslint-disable-next-line react-refresh/only-export-components
function Page() {
  const { expertId } = Route.useParams()
  return (
    <AccessGate admin>
      <ExpertEditor expertId={expertId} />
    </AccessGate>
  )
}
