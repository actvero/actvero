import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { SkillsPage } from '@/features/skills/page'

export const Route = createFileRoute('/_authenticated/skills/')({
  component: () => (
    <AccessGate admin>
      <SkillsPage />
    </AccessGate>
  ),
})
