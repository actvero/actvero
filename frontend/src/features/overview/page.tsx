import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  RefreshCw,
  Network,
  Users,
  Plug,
  PackageOpen,
  Activity,
  Coins,
  Hash,
} from 'lucide-react'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
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
import { auditActions } from '@/features/audit/actions'
import { useOrganization } from '@/features/auth/session'
import { TrendChart } from '@/features/llm-calls/dashboard-charts'
import { readCallSearch } from '@/features/llm-calls/search'
import { readMyModelSearch } from '@/features/my-models/search'
import { QuotaWindow, Points } from '@/features/usage/quota-windows'

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
function OrganizationOverview() {
  const { organization, user } = useOrganization()
  const [range, setRange] = useState(() => {
    const now = Date.now()
    return {
      from: new Date(now - 86400000).toISOString(),
      to: new Date(now).toISOString(),
    }
  })
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, 'overview'],
    queryFn: ({ signal }) =>
      api<Schema['OrganizationOverview']>(
        '/overview',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const params = new URLSearchParams({
    ...range,
    timezone: 'UTC',
    source: 'member',
    granularity: 'hour',
  })
  const usage = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'overview-usage',
      params.toString(),
    ],
    queryFn: ({ signal }) =>
      api<Schema['UsageDashboard']>(
        `/llm/dashboard?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const snapshot = query.data
  const summary = usage.data?.summary
  const blocked = denied(query.error) || denied(usage.error)
  return (
    <PageShell
      title='概览'
      description={organization.name}
      action={
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='outline'
            disabled={query.isFetching || usage.isFetching}
            onClick={() => {
              void query.refetch()
              const now = Date.now()
              setRange({
                from: new Date(now - 86400000).toISOString(),
                to: new Date(now).toISOString(),
              })
            }}
          >
            <RefreshCw />
            刷新
          </Button>
          <Button asChild>
            <Link to='/llm-usage' search={readCallSearch({})}>
              数据看板
            </Link>
          </Button>
        </div>
      }
    >
      {blocked ? (
        <RequestError error={query.error || usage.error} />
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
            summary &&
            usage.data && (
              <>
                <div className='flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
                  <Badge variant='outline'>近24小时 · 正式调用</Badge>
                  <span>
                    {dateTime(range.from)} 至 {dateTime(range.to)}
                  </span>
                </div>
                <MetricGrid label='概览指标'>
                  <MetricCard
                    title='模型调用'
                    value={String(summary.calls)}
                    note={`上游尝试 ${summary.attempts} 次`}
                    icon={Hash}
                  />
                  <MetricCard
                    title='已结算积分'
                    value={summary.settled_points ?? '不适用'}
                    note='按历史比例，不含预占与待核对'
                    icon={Coins}
                  />
                  <MetricCard
                    title='调用结果成功率'
                    value={
                      summary.calls
                        ? `${(((summary.result_counts.success || 0) / summary.calls) * 100).toFixed(2)}%`
                        : '—'
                    }
                    note='全部受理调用为分母'
                    icon={Activity}
                  />
                  <MetricCard
                    title='平均耗时'
                    value={
                      usage.data.performance.average_ms === null
                        ? '—'
                        : `${(usage.data.performance.average_ms / 1000).toFixed(2)}s`
                    }
                    note={`有记录耗时样本 ${usage.data.performance.samples} / ${summary.calls}`}
                    icon={Activity}
                  />
                </MetricGrid>
                <TrendChart
                  title='近24小时调用趋势'
                  timeline={usage.data.timeline}
                  metric='calls'
                  chart='area'
                  zone={
                    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
                  }
                />
              </>
            )
          )}
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            snapshot && (
              <>
                <MetricGrid label='组织资源'>
                  {[
                    {
                      name: '模型',
                      icon: Network,
                      value: snapshot.models,
                      note: '已开放 / 未归档',
                      to: '/models' as const,
                    },
                    {
                      name: '渠道',
                      icon: Network,
                      value: snapshot.channels,
                      note: '已启用 / 未归档；不代表测试通过',
                      to: '/model-channels' as const,
                    },
                    {
                      name: 'Skills',
                      icon: PackageOpen,
                      value: snapshot.skills,
                      note: '已发布 / 已上传',
                      to: '/skills' as const,
                    },
                    {
                      name: 'MCP 服务',
                      icon: Plug,
                      value: snapshot.mcp,
                      note: '已启用 / 已配置',
                      to: '/mcp' as const,
                    },
                    {
                      name: '成员',
                      icon: Users,
                      value: snapshot.members,
                      note: '正常 / 当前组织成员',
                      to: '/users' as const,
                    },
                  ].map((item) => (
                    <Card key={item.name} interactive asChild>
                      <Link to={item.to}>
                        <CardHeader>
                          <CardTitle className='flex items-center gap-2'>
                            <item.icon />
                            {item.name}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className='text-2xl font-semibold'>
                            {item.value.enabled} / {item.value.total}
                          </p>
                          <p className='mt-2 text-xs text-muted-foreground'>
                            {item.note}
                          </p>
                        </CardContent>
                      </Link>
                    </Card>
                  ))}
                </MetricGrid>
                <div className='grid gap-4 lg:grid-cols-2'>
                  <Card>
                    <CardHeader>
                      <CardTitle>待处理与当前状态</CardTitle>
                      <CardDescription>
                        截至 {dateTime(snapshot.as_of)} · 当前组织
                      </CardDescription>
                    </CardHeader>
                    <CardContent className='grid gap-4'>
                      <div className='flex flex-wrap items-center justify-between gap-2'>
                        <span>
                          待核对模型调用{' '}
                          <strong>{snapshot.review_calls}</strong>
                        </span>
                        <Button asChild variant='outline' size='sm'>
                          <Link
                            to='/llm-calls'
                            search={readCallSearch({
                              source: 'member',
                              settlement_status: 'review',
                            })}
                          >
                            查看调用
                          </Link>
                        </Button>
                      </div>
                      <p className='text-sm'>
                        MCP 探测：正常 {snapshot.mcp_checked} · 异常{' '}
                        {snapshot.mcp_failed} · 未检测/已过期{' '}
                        {snapshot.mcp_unchecked}
                      </p>
                      <p className='text-xs text-muted-foreground'>
                        仅当前管理员的个人凭据或共享凭据探测；不会自动发起测试。
                      </p>
                      <div className='grid grid-cols-2 gap-3 border-t pt-4'>
                        <p className='text-sm'>
                          近24小时 MCP 调用{' '}
                          <strong>{snapshot.mcp_calls}</strong>
                        </p>
                        <p className='text-sm'>
                          近24小时技能分发{' '}
                          <strong>{snapshot.skill_distributions}</strong>
                        </p>
                      </div>
                      <p className='text-xs text-muted-foreground'>
                        技能分发记录代表下载交付，不代表已安装。
                      </p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle>最近操作</CardTitle>
                      <CardDescription>
                        当前组织的最近5条管理记录
                      </CardDescription>
                    </CardHeader>
                    <CardContent className='grid gap-3'>
                      {snapshot.activities.length ? (
                        snapshot.activities.map((item, index) => (
                          <div
                            key={index}
                            className='flex flex-wrap justify-between gap-2 border-b pb-3 last:border-0'
                          >
                            <div className='min-w-0 text-sm'>
                              <p className='break-words'>
                                {item.actor} ·{' '}
                                {auditActions[item.action] || item.action}
                              </p>
                              <p className='break-words text-muted-foreground'>
                                {item.target}
                              </p>
                            </div>
                            <time className='text-xs text-muted-foreground'>
                              {dateTime(item.at)}
                            </time>
                          </div>
                        ))
                      ) : (
                        <p className='text-sm text-muted-foreground'>
                          暂无操作记录
                        </p>
                      )}
                      <Button
                        asChild
                        variant='link'
                        className='justify-self-start'
                      >
                        <Link to='/audit'>查看操作记录</Link>
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              </>
            )
          )}
        </>
      )}
    </PageShell>
  )
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
