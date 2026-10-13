import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { MemberServiceCard } from './member-service-card'
import { useMcp } from './shared'

export function MemberMcpPage() {
  const { key } = useMcp()
  const query = useQuery<Schema['McpServicePage']>({
    queryKey: [...key, 'services'],
    queryFn: ({ signal }) =>
      api<Schema['McpServicePage']>(
        '/mcp/services',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })

  return (
    <PageShell title='可用 MCP 服务'>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : query.data.items.filter((service) => service.enabled).length ? (
        <div className='flex flex-col gap-4'>
          {query.data.items
            .filter((service) => service.enabled)
            .map((service) => (
              <MemberServiceCard key={service.id} service={service} />
            ))}
        </div>
      ) : (
        <Alert>
          <AlertDescription>当前没有可用的 MCP 服务。</AlertDescription>
        </Alert>
      )}
    </PageShell>
  )
}
