import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { SkillDistributions } from '@/features/skills/distributions'

export const Route = createFileRoute('/_authenticated/skill-distributions')({
  validateSearch: (search: Record<string, unknown>) => ({
    skill:
      typeof search.skill === 'string' && /^[0-9a-f-]{36}$/i.test(search.skill)
        ? search.skill
        : undefined,
  }),
  component: Page,
})
// eslint-disable-next-line react-refresh/only-export-components
function Page() {
  const { skill } = Route.useSearch()
  return (
    <AccessGate admin>
      <SkillDistributions key={skill} skill={skill} />
    </AccessGate>
  )
}
