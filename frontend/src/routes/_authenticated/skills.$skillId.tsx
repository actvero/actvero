import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { SkillDetail } from '@/features/skills/detail'

export const Route = createFileRoute('/_authenticated/skills/$skillId')({
  component: Page,
})
// eslint-disable-next-line react-refresh/only-export-components
function Page() {
  const { skillId } = Route.useParams()
  return (
    <AccessGate admin>
      <SkillDetail skillId={skillId} />
    </AccessGate>
  )
}
