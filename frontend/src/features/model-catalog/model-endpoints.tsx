import { useQuery } from '@tanstack/react-query'
import { Copy, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import { Textarea } from '@/components/ui/textarea'
import { CopyableField } from '@/components/copyable-field'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { endpointReasonLabel } from './endpoint-status'
import { kinds, type Model } from './model-form'

const declarations = {
  unknown: '模型能力待确认',
  supported: '模型已声明支持',
  unsupported: '模型已声明不支持',
}

export function ModelEndpointsPanel({
  model,
  dirty = false,
  configuredOnly = false,
}: {
  model?: Pick<Model, 'id' | 'version'>
  dirty?: boolean
  configuredOnly?: boolean
}) {
  const { organization } = useOrganization()
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-endpoints',
      model?.id,
      model?.version,
    ],
    enabled: Boolean(model),
    queryFn: ({ signal }) =>
      api<Schema['ModelEndpoints']>(
        `/llm/models/${model!.id}/endpoints`,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
  })
  const stale = model && query.data && query.data.version !== model.version
  return (
    <Card>
      <CardHeader className='flex flex-wrap items-center justify-between gap-2'>
        <CardTitle>客户端调用端点</CardTitle>
        {model && (
          <Button
            type='button'
            size='sm'
            variant='outline'
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <RefreshCw />
            刷新端点状态
          </Button>
        )}
      </CardHeader>
      <CardContent className='flex min-w-0 flex-col gap-4'>
        {!model ? (
          <p className='text-sm text-muted-foreground'>
            保存模型后可查看调用端点。
          </p>
        ) : query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : stale ? (
          <Alert>
            <AlertDescription>
              模型配置已更新。请重新加载模型配置，再查看对应的端点与示例。
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <p className='text-sm text-muted-foreground'>
              根据已保存的配置显示。实际调用还需满足当前成员权限与额度。
            </p>
            {dirty && (
              <Alert>
                <AlertDescription>
                  当前修改尚未保存，以下仍为已保存配置的端点。
                </AlertDescription>
              </Alert>
            )}
            <div className='grid min-w-0 gap-4 lg:grid-cols-2'>
              {query.data.endpoints
                .filter(
                  (endpoint) =>
                    !configuredOnly ||
                    !(endpoint.reasons ?? []).includes(
                      'operation_not_configured'
                    )
                )
                .map((endpoint) => (
                  <EndpointCard
                    key={endpoint.operation}
                    endpoint={endpoint}
                    dirty={dirty}
                  />
                ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function EndpointCard({
  endpoint,
  dirty,
}: {
  endpoint: Schema['ClientEndpoint']
  dirty: boolean
}) {
  const label = kinds[endpoint.operation]
  const reasons = endpoint.reasons ?? []
  const configured = !reasons.includes('operation_not_configured')
  const example = JSON.stringify(endpoint.example, null, 2)
  async function copy() {
    try {
      await navigator.clipboard.writeText(example)
      toast.success('已复制请求示例')
    } catch {
      toast.error('复制失败，请选择文本后复制')
    }
  }
  return (
    <div className='flex min-w-0 flex-col gap-3 rounded-lg border p-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <span className='text-sm font-medium'>{label}</span>
        <Badge variant={endpoint.open ? 'success' : 'outline'}>
          {endpoint.open ? '配置就绪' : configured ? '暂不可用' : '未配置'}
        </Badge>
      </div>
      <CopyableField
        label={`${label}端点`}
        copyLabel={`复制${label}端点`}
        value={`${endpoint.method} ${endpoint.path}`}
      />
      {endpoint.operation === 'chat' && configured && (
        <div className='flex flex-col gap-1 text-sm text-muted-foreground'>
          <span>
            流式：{declarations[endpoint.stream_declaration ?? 'unknown']}
          </span>
          <span>
            工具调用：{declarations[endpoint.tools_declaration ?? 'unknown']}
          </span>
        </div>
      )}
      {reasons.length > 0 && (
        <ul className='list-inside list-disc text-sm text-muted-foreground'>
          {reasons.map((reason) => (
            <li key={reason}>{endpointReasonLabel(reason)}</li>
          ))}
        </ul>
      )}
      {endpoint.open && !dirty && (
        <CollapsibleSection title={`${label}请求示例`}>
          <div className='flex flex-col gap-3'>
            <Textarea
              aria-label={`${label}请求 JSON`}
              value={example}
              readOnly
              rows={6}
            />
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => void copy()}
            >
              <Copy />
              复制{label}请求示例
            </Button>
          </div>
        </CollapsibleSection>
      )}
    </div>
  )
}
