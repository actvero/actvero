import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowUpRight,
  BookOpen,
  Bot,
  CircleAlert,
  Coins,
  Hash,
  LayoutTemplate,
  Network,
  PackageOpen,
  Plug,
  RefreshCw,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { auditActions } from '@/features/audit/actions'
import { useOrganization } from '@/features/auth/session'
import { TrendChart } from '@/features/llm-calls/dashboard-charts'
import { readCallSearch } from '@/features/llm-calls/search'
import { Points } from '@/features/usage/quota-windows'

type Snapshot = Schema['OrganizationOverview']
const format = new Intl.NumberFormat('zh-CN')
const number = (value?: number) => (value == null ? '—' : format.format(value))
const reportAccessDenied = (error: unknown) =>
  error instanceof ApiError && [401, 403].includes(error.status)

function Icon({
  icon: Symbol,
  tone = 'neutral',
}: {
  icon: LucideIcon
  tone?: 'neutral' | 'info' | 'success' | 'warning'
}) {
  const tones = {
    neutral: 'bg-muted text-muted-foreground',
    info: 'bg-info/10 text-info',
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/15 text-foreground',
  }
  return (
    <span
      className={cn(
        'inline-flex size-7 shrink-0 items-center justify-center rounded-md',
        tones[tone]
      )}
    >
      <Symbol className='size-4' aria-hidden />
    </span>
  )
}

function Summary({
  snapshot,
  used,
}: {
  snapshot?: Snapshot
  used?: Schema['UsageSummary']
}) {
  const metrics = [
    {
      label: '活跃成员',
      icon: Users,
      tone: 'info',
      value: number(snapshot?.active_members),
      help: '近 24 小时通过桌面端或访问密钥发起模型或 MCP 工具调用的当前成员；按成员去重。',
    },
    {
      label: '模型调用',
      icon: Hash,
      tone: 'neutral',
      value: number(used?.calls),
      help: '统计正式受理的模型调用，包含知识库索引和检索；不包含管理员测试。',
    },
    {
      label: 'MCP 工具调用',
      icon: Plug,
      tone: 'warning',
      value: number(snapshot?.mcp_tool_calls),
      help: '通过桌面端或访问密钥发起的工具调用。',
    },
    {
      label: '已结算积分',
      icon: Coins,
      tone: 'success',
      value:
        used?.settled_points == null ? (
          '—'
        ) : (
          <Points value={used.settled_points} />
        ),
      help: '按调用时的积分换算统计，不含预占与待核对。',
    },
  ] as const
  return (
    <section aria-label='使用概况' className='flex min-w-0 flex-col gap-3'>
      <div className='flex items-center justify-between gap-3'>
        <h2 className='text-base font-semibold'>使用概况</h2>
        <span className='text-sm text-muted-foreground'>近 24 小时</span>
      </div>
      <dl className='grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border @3xl/content:grid-cols-4'>
        {metrics.map(({ label, icon, tone, value, help }) => (
          <div
            className='flex min-w-0 flex-col gap-2 bg-card px-3 py-3 sm:px-4'
            key={label}
          >
            <dt
              className='flex min-w-0 items-center gap-2 text-sm font-medium text-muted-foreground'
              title={help}
            >
              <Icon icon={icon} tone={tone} />
              <span>{label}</span>
            </dt>
            <dd className='text-2xl font-semibold break-all tabular-nums'>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function AttentionRow({
  title,
  detail,
  children,
}: {
  title: string
  detail: string
  children: ReactNode
}) {
  return (
    <li className='flex flex-wrap items-center justify-between gap-2 px-4 py-2'>
      <div className='min-w-0 text-sm'>
        <span className='font-medium'>{title}</span>
        <span className='ms-2 break-words text-muted-foreground'>{detail}</span>
      </div>
      <div className='ms-auto flex flex-wrap gap-1'>{children}</div>
    </li>
  )
}

function Attention({ snapshot }: { snapshot: Snapshot }) {
  const {
    expert_attention: expert,
    knowledge_attention: knowledge,
    mcp_attention: mcp,
    review_calls: review,
  } = snapshot
  if (!expert && !knowledge && !mcp && !review) return null
  return (
    <section
      aria-labelledby='overview-attention'
      className='overflow-hidden rounded-xl border'
    >
      <div className='flex items-center gap-2 border-b bg-warning/5 px-4 py-2.5'>
        <Icon icon={CircleAlert} tone='warning' />
        <h2 id='overview-attention' className='text-base font-semibold'>
          需要处理
        </h2>
      </div>
      <ul className='divide-y'>
        {expert && (
          <AttentionRow
            title={`${number(expert.count)} 个已发布专家有依赖问题`}
            detail={expert.name}
          >
            {expert.count > 1 && (
              <Button asChild variant='ghost' size='sm'>
                <Link to='/experts'>查看列表</Link>
              </Button>
            )}
            <Button asChild variant='outline' size='sm'>
              <Link
                to='/experts/$expertId'
                params={{ expertId: expert.resource_id }}
              >
                检查专家
              </Link>
            </Button>
          </AttentionRow>
        )}
        {knowledge && (
          <AttentionRow
            title={`${number(knowledge.count)} 份文档处理需要关注`}
            detail={knowledge.name}
          >
            {knowledge.count > 1 && (
              <Button asChild variant='ghost' size='sm'>
                <Link to='/knowledge' search={{}}>
                  知识库列表
                </Link>
              </Button>
            )}
            <Button asChild variant='outline' size='sm'>
              <Link
                to='/knowledge'
                search={{ base: knowledge.resource_id, tab: 'queue' }}
              >
                查看队列
              </Link>
            </Button>
          </AttentionRow>
        )}
        {mcp && (
          <AttentionRow
            title={`${number(mcp.count)} 个 MCP 服务连接异常`}
            detail={mcp.name}
          >
            {mcp.count > 1 && (
              <Button asChild variant='ghost' size='sm'>
                <Link to='/mcp'>查看列表</Link>
              </Button>
            )}
            <Button asChild variant='outline' size='sm'>
              <Link to='/mcp' search={{ service: mcp.resource_id }}>
                检查服务
              </Link>
            </Button>
          </AttentionRow>
        )}
        {review > 0 && (
          <AttentionRow
            title={`${number(review)} 笔模型调用待核对`}
            detail='计量与结算'
          >
            <Button asChild variant='outline' size='sm'>
              <Link
                to='/llm-calls'
                search={readCallSearch({
                  source: 'all',
                  settlement_status: 'review',
                })}
              >
                查看调用
              </Link>
            </Button>
          </AttentionRow>
        )}
      </ul>
    </section>
  )
}

function Resources({ snapshot }: { snapshot: Snapshot }) {
  const { experts, models, skills, mcp, knowledge, workbenches } = snapshot
  const entries = [
    {
      name: '专家',
      icon: Bot,
      to: '/experts',
      status: `${number(experts.enabled)} 个已发布`,
      detail: snapshot.experts_with_changes
        ? `${number(snapshot.experts_with_changes)} 个有未发布修改`
        : '',
    },
    {
      name: '模型',
      icon: Network,
      to: '/models',
      status: `${number(models.enabled)} 个已开放`,
      detail: `${number(snapshot.channels.enabled)} 个已启用渠道`,
    },
    {
      name: 'Skills',
      icon: PackageOpen,
      to: '/skills',
      status: `${number(skills.enabled)} 个已发布`,
      detail: '',
    },
    {
      name: 'MCP',
      icon: Plug,
      to: '/mcp',
      status: `${number(mcp.enabled)} 个已启用`,
      detail: '',
    },
    {
      name: '知识库',
      icon: BookOpen,
      to: '/knowledge',
      status: `${number(knowledge.total)} 个知识库 · ${number(knowledge.documents)} 份文档`,
      detail: knowledge.processing
        ? `${number(knowledge.processing)} 份处理中`
        : '',
    },
    {
      name: '工作台',
      icon: LayoutTemplate,
      to: '/workbenches',
      status: `${number(workbenches.enabled)} 个已发布`,
      detail: snapshot.workbenches_with_drafts
        ? `${number(snapshot.workbenches_with_drafts)} 个有草稿`
        : '',
    },
  ] as const
  return (
    <section
      aria-labelledby='overview-resources'
      className='flex flex-col gap-3'
    >
      <h2 id='overview-resources' className='text-base font-semibold'>
        组织能力
      </h2>
      <div className='grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border @2xl/content:grid-cols-3'>
        {entries.map(({ name, icon, to, status, detail }) => (
          <Link
            key={to}
            to={to}
            className='group flex min-w-0 items-start gap-2.5 bg-card p-3 text-sm hover:bg-accent focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring sm:p-4'
          >
            <Icon icon={icon} />
            <div className='flex min-w-0 flex-1 flex-col gap-1'>
              <div className='font-medium'>{name}</div>
              <div className='text-xs text-muted-foreground'>
                {[status, detail].filter(Boolean).join(' · ')}
              </div>
            </div>
            <ArrowUpRight
              className='size-4 shrink-0 text-muted-foreground'
              aria-hidden
            />
          </Link>
        ))}
      </div>
    </section>
  )
}

function RecentChanges({ activities }: { activities: Snapshot['activities'] }) {
  return (
    <section
      aria-labelledby='overview-changes'
      className='min-w-0 overflow-hidden rounded-xl border bg-card'
    >
      <div className='flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5'>
        <h2 id='overview-changes' className='text-base font-semibold'>
          最近重要变更
        </h2>
        <Button asChild variant='ghost' size='sm'>
          <Link to='/audit'>
            操作记录 <ArrowUpRight />
          </Link>
        </Button>
      </div>
      {activities.length ? (
        <ul className='divide-y'>
          {activities.map((item, index) => (
            <li key={`${item.at}/${item.action}/${item.target_id}/${index}`}>
              <Link
                to='/audit'
                search={{ target: item.target_id, action: item.action }}
                className='block px-4 py-2.5 text-sm hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring'
              >
                <span className='block font-medium break-words'>
                  {auditActions[item.action] ?? item.action} · {item.target}
                </span>
                <span className='block text-xs break-words text-muted-foreground'>
                  {item.actor} ·{' '}
                  <time dateTime={item.at}>{dateTime(item.at)}</time>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className='px-4 py-5 text-sm text-muted-foreground'>暂无重要变更</p>
      )}
    </section>
  )
}

export function OrganizationOverview() {
  const { organization, user } = useOrganization()
  const [asOf, setAsOf] = useState(Date.now)
  const key = ['organization', organization.tenant_id, user.id, 'overview']
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<Snapshot>('/overview', 'GET', undefined, undefined, signal),
  })
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const params = new URLSearchParams({
    from: new Date(asOf - 86400000).toISOString(),
    to: new Date(asOf).toISOString(),
    timezone: zone,
    source: 'member',
    granularity: 'hour',
  })
  const usage = useQuery({
    queryKey: [...key, 'usage', params.toString()],
    queryFn: ({ signal }) =>
      api<Schema['UsageDashboard']>(
        `/llm/dashboard?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const blocked = [query.error, usage.error].find(reportAccessDenied)
  const snapshot = query.data
  return (
    <PageShell
      title='概览'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='outline'
            disabled={query.isFetching || usage.isFetching}
            onClick={() => {
              void query.refetch()
              setAsOf(Date.now())
            }}
          >
            <RefreshCw />
            刷新
          </Button>
          <Button variant='outline' asChild>
            <Link to='/llm-usage' search={readCallSearch({})}>
              数据看板 <ArrowUpRight />
            </Link>
          </Button>
        </div>
      }
    >
      {blocked ? (
        <RequestError error={blocked} />
      ) : (
        <>
          <Summary
            snapshot={query.isError ? undefined : snapshot}
            used={usage.isError ? undefined : usage.data?.summary}
          />
          {query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : snapshot ? (
            <>
              <Attention snapshot={snapshot} />
              <Resources snapshot={snapshot} />
            </>
          ) : (
            <LoadingState />
          )}
          <div className='grid min-w-0 items-start gap-4 @4xl/content:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'>
            {usage.isError ? (
              <RequestError
                error={usage.error}
                retry={() => void usage.refetch()}
              />
            ) : usage.data ? (
              <TrendChart
                title='近24小时调用趋势'
                timeline={usage.data.timeline}
                metric='calls'
                chart='area'
                zone={zone}
                compact
              />
            ) : (
              <LoadingState />
            )}
            {snapshot && !query.isError && (
              <RecentChanges activities={snapshot.activities} />
            )}
          </div>
        </>
      )}
    </PageShell>
  )
}
