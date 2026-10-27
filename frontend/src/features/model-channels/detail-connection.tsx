import { dateTime } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { channelBaseUrl } from './channel-address'
import { apiLabels, type ProviderModule } from './provider-modules'
import type { Detail } from './shared'
import { operationLabels, type TestOperation } from './test-operations'

export function DetailConnection({
  channel,
  provider,
  showHistory,
}: {
  channel: Detail
  provider?: ProviderModule
  showHistory: () => void
}) {
  const diagnostic = channel.last_diagnostic
  return (
    <div className='flex min-w-0 flex-col gap-4 pt-4'>
      <Card>
        <CardHeader>
          <CardTitle>连接信息</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-4'>
          <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-4 gap-y-3 text-sm'>
            <dt className='text-muted-foreground'>BaseURL</dt>
            <dd className='font-mono break-all'>
              {channelBaseUrl(provider, channel)}
            </dd>
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
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>最近目录与诊断</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-4'>
          <div className='flex flex-col gap-1 text-sm'>
            <p className='font-medium'>最近目录检查</p>
            {provider && !provider.model_discovery ? (
              <p className='text-muted-foreground'>
                当前供应商没有目录接口，可手动添加模型。
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
