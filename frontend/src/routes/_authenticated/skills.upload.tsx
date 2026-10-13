import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { api } from '@/lib/api'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { AccessGate } from '@/features/auth/gate'
import { useSkills, type Skill } from '@/features/skills/shared'
import { UploadWizard } from '@/features/skills/upload'

export const Route = createFileRoute('/_authenticated/skills/upload')({
  validateSearch: (search: Record<string, unknown>): { skill?: string } => ({
    skill:
      typeof search.skill === 'string' && /^[0-9a-f-]{36}$/i.test(search.skill)
        ? search.skill
        : undefined,
  }),
  component: () => (
    <AccessGate admin>
      <Page />
    </AccessGate>
  ),
})
// eslint-disable-next-line react-refresh/only-export-components
function Page() {
  const { skill } = Route.useSearch()
  const { key } = useSkills()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: [...key, skill],
    enabled: !!skill,
    queryFn: ({ signal }) =>
      api<Skill>(`/skills/${skill}`, 'GET', undefined, undefined, signal),
  })
  if (skill && query.isPending)
    return (
      <PageShell title='上传新版本'>
        <LoadingState />
      </PageShell>
    )
  if (skill && query.isError)
    return (
      <PageShell title='上传新版本'>
        <RequestError error={query.error} retry={() => void query.refetch()} />
      </PageShell>
    )
  return (
    <UploadWizard
      skill={query.data}
      close={() => {
        void navigate(
          skill
            ? { to: '/skills/$skillId', params: { skillId: skill } }
            : { to: '/skills' }
        )
      }}
    />
  )
}
