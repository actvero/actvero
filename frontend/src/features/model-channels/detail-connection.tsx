import { useQuery } from '@tanstack/react-query'
import { api, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { apiLabels, type ProviderModule } from './provider-modules'
import type { Detail } from './shared'
import { operationLabels, type TestOperation } from './test-operations'

const addressMode = {
  provider_default: '官方预设地址',
  service_root: '自定义地址',
  legacy_api_base: '自定义地址',
}

export function DetailConnection({
  channel,
  provider,
  showHistory,
}: {
  channel: Detail
  provider?: ProviderModule
  showHistory: () => void
}) {
  const { csrf, organization } = useOrganization()
  // The CSRF token authenticates the pure preview request but must not enter a cache key.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const preview = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'channel-address-preview',
      channel.id,
      channel.version,
      channel.provider,
      channel.connection,
    ],
    queryFn: ({ signal }) =>
      api<Schema['ResolvedConnection']>(
        '/llm/channel-addresses/resolve',
        'POST',
        { provider: channel.provider, connection: channel.connection },
        csrf,
        signal
      ),
  })
  const diagnostic = channel.last_diagnostic
  return (
    <div className='flex min-w-0 flex-col gap-4 pt-4'>
      <Card>
        <CardHeader>
          <CardTitle>连接信息</CardTitle>
          <CardDescription>
            只读地址预览不会连接上游；密钥不在此展示。
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-col gap-4'>
          <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-4 gap-y-3 text-sm'>
            <dt className='text-muted-foreground'>地址方式</dt>
            <dd>{addressMode[channel.connection.address_mode]}</dd>
            <dt className='text-muted-foreground'>API 基础 URL</dt>
            <dd className='font-mono break-all'>
              {channel.connection.address_mode === 'legacy_api_base'
                ? channel.connection.legacy_base_url
                : (channel.connection.service_root ??
                  provider?.official_service_root ??
                  '使用内置官方地址')}
            </dd>
            <dt className='text-muted-foreground'>接口前缀</dt>
            <dd className='font-mono break-all'>
              {channel.connection.address_mode === 'legacy_api_base'
                ? '按已配置的 API 基础 URL 解析'
                : channel.connection.api_prefix === null ||
                    channel.connection.api_prefix === undefined
                  ? provider?.default_api_prefix || '根路径'
                  : channel.connection.api_prefix || '根路径'}
            </dd>
            <dt className='text-muted-foreground'>兼容 Base URL</dt>
            <dd className='font-mono break-all'>{channel.base_url}</dd>
            <dt className='text-muted-foreground'>身份认证</dt>
            <dd>
              {channel.auth_mode === 'none'
                ? '无认证'
                : channel.credential_configured
                  ? 'API Key · 已配置'
                  : 'API Key · 未配置'}
            </dd>
            <dt className='text-muted-foreground'>请求超时</dt>
            <dd>{channel.timeout_seconds} 秒</dd>
            <dt className='text-muted-foreground'>允许接口</dt>
            <dd className='flex flex-wrap gap-2'>
              {channel.declared_apis.map((item) => (
                <Badge variant='outline' key={item}>
                  {apiLabels[item] ?? item}
                </Badge>
              ))}
              {!channel.declared_apis.length && '未开启'}
            </dd>
            <dt className='text-muted-foreground'>创建时间</dt>
            <dd>{dateTime(channel.created_at)}</dd>
          </dl>
          {provider?.setup_help && (
            <Alert>
              <AlertTitle>接入说明</AlertTitle>
              <AlertDescription>{provider.setup_help}</AlertDescription>
            </Alert>
          )}
          <Separator />
          <div className='flex min-w-0 flex-col gap-2'>
            <p className='text-sm font-medium'>有效目标预览</p>
            {preview.isPending ? (
              <LoadingState />
            ) : preview.isError ? (
              <RequestError
                error={preview.error}
                retry={() => void preview.refetch()}
              />
            ) : (
              preview.data && (
                <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm'>
                  <dt className='text-muted-foreground'>模型目录</dt>
                  <dd className='min-w-0 break-words'>
                    {preview.data.directory_url
                      ? `${preview.data.directory_method} ${preview.data.directory_url}`
                      : provider?.reference_catalog
                        ? '此套餐不提供模型目录；可在编辑渠道时搜索参考模型或输入实际模型 ID，并单独测试。'
                        : '当前预设暂未接入模型目录，请手动登记模型 ID；可单独进行调用诊断。'}
                  </dd>
                  {preview.data.operation_targets.map((target) => (
                    <div
                      key={target.operation}
                      className='col-span-2 grid grid-cols-[6rem_minmax(0,1fr)] gap-x-4'
                    >
                      <dt className='text-muted-foreground'>
                        {operationLabels[target.operation as TestOperation] ??
                          target.operation}
                      </dt>
                      <dd className='font-mono break-all'>
                        {target.method} {target.url}
                      </dd>
                    </div>
                  ))}
                </dl>
              )
            )}
            <p className='text-xs text-muted-foreground'>
              模型相关路径仅供预览；实际调用按所选上游模型解析。
            </p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>最近目录与诊断</CardTitle>
          <CardDescription>
            目录可读和模型调用成功分别记录，均不代表成员已获授权。
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-col gap-4'>
          <div className='flex flex-col gap-1 text-sm'>
            <p className='font-medium'>最近目录检查</p>
            {provider && !provider.model_discovery ? (
              <p className='text-muted-foreground'>
                {provider.reference_catalog
                  ? '此套餐不提供模型目录；请登记模型并单独测试。'
                  : '此预设暂未接入模型目录；请手动登记模型。'}
              </p>
            ) : channel.last_check ? (
              <p>
                {dateTime(channel.last_check.at)} ·{' '}
                {channel.last_check.ok ? '读取成功' : '读取失败'} ·{' '}
                {channel.last_check.message}
              </p>
            ) : (
              <p className='text-muted-foreground'>尚未读取目录</p>
            )}
          </div>
          <Separator />
          <div className='flex flex-col gap-1 text-sm'>
            <p className='font-medium'>最近调用诊断</p>
            {diagnostic ? (
              <>
                <p>
                  {dateTime(diagnostic.at)} · {diagnostic.upstream_model_id} ·{' '}
                  {operationLabels[diagnostic.operation as TestOperation] ??
                    diagnostic.operation}
                </p>
                <p>
                  {diagnostic.status === 'success'
                    ? '成功'
                    : diagnostic.status === 'failure'
                      ? '失败'
                      : '结果未确认'}{' '}
                  · {diagnostic.duration_ms ?? '—'} ms{' '}
                  {diagnostic.stale && '· 旧配置'}
                </p>
                <Button
                  type='button'
                  variant='link'
                  size='sm'
                  className='self-start p-0'
                  onClick={showHistory}
                >
                  查看测试历史
                </Button>
              </>
            ) : (
              <p className='text-muted-foreground'>尚无诊断记录</p>
            )}
          </div>
        </CardContent>
      </Card>
      {channel.archived && (
        <Alert>
          <AlertTitle>渠道已归档</AlertTitle>
          <AlertDescription>
            历史配置仍可查看；恢复后才能检查目录、登记模型或测试。
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
