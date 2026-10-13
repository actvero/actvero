import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Upload, Download } from 'lucide-react'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageShell } from '@/components/layout/page-shell'
import { RequestError, LoadingState } from '@/components/request-state'
import { ImportDialog } from './import-dialog'
import { ServiceCard } from './service-card'
import { ServiceEditor } from './service-editor'
import { useMcp } from './shared'

export function McpPage() {
  const { key } = useMcp()
  const [q, setQ] = useState('')
  const [add, setAdd] = useState(false)
  const [importing, setImporting] = useState(false)
  const query = useQuery<Schema['McpServicePage']>({
    queryKey: [...key, 'services'],
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (s) => s.enabled && s.connection_options?.health_enabled
      )
        ? 15000
        : false,
    queryFn: ({ signal }) =>
      api<Schema['McpServicePage']>(
        '/mcp/services',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  async function exportData() {
    try {
      const data = await api<Schema['McpImport']>('/mcp/export')
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      )
      const a = document.createElement('a')
      a.href = url
      a.download = 'actvero-mcp-services.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(messageOf(e))
    }
  }
  const oauth = new URLSearchParams(window.location.search).get('oauth')
  return (
    <PageShell
      title='MCP 服务'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button variant='outline' onClick={() => void exportData()}>
            <Download data-icon='inline-start' />
            导出
          </Button>
          <Button variant='outline' onClick={() => setImporting(true)}>
            <Upload data-icon='inline-start' />
            导入
          </Button>
          <Button onClick={() => setAdd(true)}>
            <Plus data-icon='inline-start' />
            添加服务
          </Button>
        </div>
      }
    >
      {oauth && (
        <Alert>
          <AlertDescription>
            {oauth === 'connected'
              ? '授权已保存，已读取能力目录。'
              : oauth === 'discovery_failed'
                ? '授权已保存，读取能力失败，请在服务菜单中重试。'
                : '授权未完成，请重新连接。'}
          </AlertDescription>
        </Alert>
      )}
      <Input
        className='sm:max-w-sm'
        aria-label='搜索 MCP 服务'
        placeholder='搜索服务名称或说明…'
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <div className='flex flex-col gap-4'>
          {query.data.items
            .filter((s) =>
              (s.name + (s.display_name || '') + s.description)
                .toLowerCase()
                .includes(q.toLowerCase())
            )
            .map((s) => (
              <ServiceCard key={s.id} service={s} />
            ))}
          {!query.data.items.length && (
            <Alert>
              <AlertDescription>
                还没有 MCP 服务。添加服务地址或导入配置开始连接。
              </AlertDescription>
            </Alert>
          )}
          {!!query.data.items.length &&
            !query.data.items.some((s) =>
              (s.name + (s.display_name || '') + s.description)
                .toLowerCase()
                .includes(q.toLowerCase())
            ) && (
              <p className='py-8 text-center text-muted-foreground'>
                没有符合条件的服务
              </p>
            )}
        </div>
      )}
      {add && <ServiceEditor close={() => setAdd(false)} />}{' '}
      {importing && <ImportDialog close={() => setImporting(false)} />}
    </PageShell>
  )
}
