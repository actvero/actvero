import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { RefreshCw, Activity, Coins, Hash } from 'lucide-react'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from '@/components/ui/card'
import { PageShell } from '@/components/layout/page-shell'
import { MetricGrid } from '@/components/metric-grid'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { readMyModelSearch } from '@/features/my-models/search'
import { QuotaWindow, Points } from '@/features/usage/quota-windows'
import { OrganizationOverview } from './organization-overview'

export function OverviewPage() {
  const { organization, user } = useOrganization()
  return organization.role === 'administrator' ? (
    <OrganizationOverview key={`${organization.tenant_id}/${user.id}`} />
  ) : (
    <MemberOverview key={`${organization.tenant_id}/${user.id}`} />
  )
}
function MetricCard({
  title,
  value,
  note,
  icon: Icon,
}: {
  title: string
  value: string
  note: string
  icon: typeof Hash
}) {
  return (
    <Card density='compact' className='min-w-0'>
      <CardHeader className='pb-2'>
        <CardTitle size='body' className='flex items-center gap-2'>
          <Icon />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className='pb-2'>
        <p className='text-3xl font-semibold break-words tabular-nums'>
          {value}
        </p>
        <p className='mt-2 text-xs text-muted-foreground'>{note}</p>
      </CardContent>
    </Card>
  )
}
function denied(error: unknown) {
  return error instanceof ApiError && [401, 403].includes(error.status)
}
function MemberOverview() {
  const { organization, user } = useOrganization()
  const key = [
    'organization',
    organization.tenant_id,
    user.id,
    'personal-overview',
  ]
  const usage = useQuery({
    queryKey: [...key, 'usage'],
    queryFn: ({ signal }) =>
      api<Schema['PersonalOverview']>(
        '/account/overview',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const quota = useQuery({
    queryKey: [...key, 'quota'],
    queryFn: ({ signal }) =>
      api<Schema['QuotaView']>(
        '/account/llm/quota',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const models = useQuery({
    queryKey: [...key, 'models'],
    queryFn: ({ signal }) =>
      api<Schema['MemberModelPage']>(
        '/account/llm/models?page=1',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const blocked =
    denied(usage.error) || denied(quota.error) || denied(models.error)
  return (
    <PageShell
      title='我的概览'
      description={organization.name}
      action={
        <Button
          variant='outline'
          disabled={usage.isFetching || quota.isFetching || models.isFetching}
          onClick={() => {
            void usage.refetch()
            void quota.refetch()
            void models.refetch()
          }}
        >
          <RefreshCw />
          刷新
        </Button>
      }
    >
      {blocked ? (
        <RequestError
          error={[usage.error, quota.error, models.error].find(denied)}
        />
      ) : (
        <>
          {usage.isPending ? (
            <LoadingState />
          ) : usage.isError ? (
            <RequestError
              error={usage.error}
              retry={() => void usage.refetch()}
            />
          ) : (
            usage.data && (
              <MetricGrid label='本人指标'>
                <MetricCard
                  title='我的模型调用'
                  value={String(usage.data.calls)}
                  note='近24小时 · 本人的正式调用'
                  icon={Hash}
                />
                <MetricCard
                  title='我的已结算积分'
                  value={usage.data.settled_points}
                  note='近24小时 · 按历史比例'
                  icon={Coins}
                />
                <MetricCard
                  title='我的待核对调用'
                  value={String(usage.data.review_calls)}
                  note='当前全部待核对，不受日期限制'
                  icon={Activity}
                />
              </MetricGrid>
            )
          )}
          <div className='grid gap-4 lg:grid-cols-2'>
            <Card>
              <CardHeader>
                <CardTitle>我的模型额度</CardTitle>
                <CardDescription>
                  各窗口分别展示，剩余额度不跨窗口相加
                </CardDescription>
              </CardHeader>
              <CardContent className='grid gap-5'>
                {quota.isPending ? (
                  <LoadingState />
                ) : quota.isError ? (
                  <RequestError
                    error={quota.error}
                    retry={() => void quota.refetch()}
                  />
                ) : quota.data?.status === 'unconfigured' ? (
                  <Alert>
                    <AlertDescription>
                      尚未配置模型额度，请联系组织管理员。
                    </AlertDescription>
                  </Alert>
                ) : quota.data?.windows.length ? (
                  quota.data.windows.map((window, index) => (
                    <QuotaWindow key={index} window={window} />
                  ))
                ) : (
                  <p className='text-sm text-muted-foreground'>
                    当前策略没有额度窗口。
                  </p>
                )}
                <Button asChild variant='outline'>
                  <Link to='/my-usage'>查看我的用量</Link>
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>我的资源与接入</CardTitle>
                <CardDescription>以当前授权为准</CardDescription>
              </CardHeader>
              <CardContent className='grid gap-4'>
                {models.isPending ? (
                  <LoadingState />
                ) : models.isError ? (
                  <RequestError
                    error={models.error}
                    retry={() => void models.refetch()}
                  />
                ) : (
                  <p className='text-2xl font-semibold'>
                    {models.data?.total ?? 0} 个可见模型
                  </p>
                )}
                <div className='flex flex-wrap gap-2'>
                  <Button asChild>
                    <Link to='/my-models' search={readMyModelSearch({})}>
                      我的模型与接入示例
                    </Link>
                  </Button>
                  <Button asChild variant='outline'>
                    <Link to='/my-access-keys'>访问密钥</Link>
                  </Button>
                  <Button asChild variant='outline'>
                    <Link to='/mcp'>可用 MCP 服务</Link>
                  </Button>
                </div>
                <p className='text-sm text-muted-foreground'>
                  模型可见性与当前可调用状态分别判断，进入模型页查看详情。
                </p>
                {usage.data && (
                  <p className='text-sm'>
                    近24小时确认消耗{' '}
                    <Points value={usage.data.settled_points} /> 积分
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </PageShell>
  )
}
