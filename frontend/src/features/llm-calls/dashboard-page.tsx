import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  RefreshCw,
  Settings2,
  Activity,
  Hash,
  Coins,
  CircleHelp,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageShell } from '@/components/layout/page-shell'
import { MetricGrid } from '@/components/metric-grid'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { CallFilters } from './call-filters'
import { TrendChart, Ranking, FlowChart } from './dashboard-charts'
import {
  defaults,
  metricLabels,
  readPreferences,
  preferenceDefaults,
  type Display,
  type DashboardSearch,
  type Preferences,
  type Metric,
} from './dashboard-search'
import { queryFor, results, settlements, sources } from './filters'
import { searchToFilters, searchFromFilters, type CallSearch } from './search'
import { timeInZone } from './time'

export function DashboardSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Record<string, string>
  onChange: (value: string) => void
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className='w-full sm:w-auto'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {Object.entries(options).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
function PreferencesDialog({
  scope,
  current,
}: {
  scope: string
  current: Preferences
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(current)
  const [error, setError] = useState('')
  return (
    <>
      <Button
        variant='outline'
        onClick={() => {
          setDraft(readPreferences(scope))
          setError('')
          setOpen(true)
        }}
      >
        <Settings2 />
        偏好设置
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>看板默认设置</DialogTitle>
            <DialogDescription>
              保存在本浏览器，按组织与账号隔离。当前链接中的筛选优先。
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-4'>
            <label className='grid gap-2'>
              默认范围
              <DashboardSelect
                label='默认范围'
                value={String(draft.days)}
                options={{ 1: '近24小时', 7: '近7天', 30: '近30天' }}
                onChange={(value) =>
                  setDraft({ ...draft, days: Number(value) })
                }
              />
            </label>
            <label className='grid gap-2'>
              默认粒度
              <DashboardSelect
                label='默认粒度'
                value={draft.granularity}
                options={{ auto: '自动粒度', hour: '小时', day: '天' }}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    granularity: value as Display['granularity'],
                  })
                }
              />
            </label>
            <label className='grid gap-2'>
              默认指标
              <DashboardSelect
                label='默认指标'
                value={draft.metric}
                options={metricLabels}
                onChange={(value) =>
                  setDraft({ ...draft, metric: value as Metric })
                }
              />
            </label>
            <label className='grid gap-2'>
              默认图表
              <DashboardSelect
                label='默认图表'
                value={draft.chart}
                options={{ bar: '柱状图', area: '面积图', table: '数据表' }}
                onChange={(value) =>
                  setDraft({ ...draft, chart: value as Display['chart'] })
                }
              />
            </label>
            <label className='grid gap-2'>
              默认排行
              <DashboardSelect
                label='默认排行'
                value={String(draft.top)}
                options={{ 5: '前5', 10: '前10', 20: '前20', 50: '前50' }}
                onChange={(value) => setDraft({ ...draft, top: Number(value) })}
              />
            </label>
            {error && (
              <Alert variant='destructive'>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setDraft(preferenceDefaults)}
            >
              恢复默认
            </Button>
            <Button variant='outline' onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => {
                try {
                  localStorage.setItem(scope, JSON.stringify(draft))
                  toast.success('偏好已保存，下次从菜单进入时生效')
                  setOpen(false)
                } catch {
                  setError('浏览器未允许保存偏好，当前看板仍可使用。')
                }
              }}
            >
              保存偏好
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
export function LlmUsagePage({ search }: { search: DashboardSearch }) {
  const { organization, user } = useOrganization()
  return (
    <DashboardPage
      key={`${organization.tenant_id}/${user.id}`}
      search={search}
    />
  )
}
function DashboardPage({ search }: { search: DashboardSearch }) {
  const { organization, user } = useOrganization()
  const navigate = useNavigate()
  const scope = `actvero:dashboard:v1:${organization.tenant_id}:${user.id}`
  const [preferences] = useState(() => readPreferences(scope))
  const [range] = useState(() => ({
    to: new Date().toISOString(),
    from: new Date(Date.now() - preferences.days * 86400000).toISOString(),
  }))
  const [flowGraph, setFlowGraph] = useState(true)
  const zoneQuery = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'quota-default-timezone',
    ],
    enabled: !search.timezone,
    queryFn: ({ signal }) =>
      api<Schema['QuotaPolicyPage']>(
        '/quota/policies?state=current&page=1',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const zone = search.timezone || zoneQuery.data?.default_timezone || 'UTC'
  const diagnostic = search.source === 'diagnostic'
  const display = {
    ...defaults,
    ...preferences,
    ...Object.fromEntries(
      Object.entries(search).filter(([, value]) => value !== undefined)
    ),
  } as Display
  if (diagnostic && display.metric === 'points') display.metric = 'calls'
  if (diagnostic && display.rank === 'points') display.rank = 'calls'
  const effective: DashboardSearch = {
    ...search,
    ...display,
    timezone: zone,
    source: search.source === 'all' ? 'member' : search.source,
    held: false,
    from: search.from || range.from,
    to: search.to || range.to,
  }
  const params = new URLSearchParams(
    queryFor(
      { ...searchToFilters(effective), fromLocal: '', toLocal: '' },
      1,
      true
    )
  )
  params.set('from', effective.from)
  params.set('to', effective.to)
  params.set('granularity', display.granularity)
  params.set('top', String(display.top))
  params.set('rank', display.rank)
  if (display.selected_members)
    params.set('selected_members', display.selected_members)
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'llm-dashboard',
      params.toString(),
    ],
    enabled: Boolean(search.timezone) || zoneQuery.isSuccess,
    queryFn: ({ signal }) =>
      api<Schema['UsageDashboard']>(
        `/llm/dashboard?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const update = (values: Partial<DashboardSearch>) =>
    void navigate({
      to: '/llm-usage',
      search: { ...effective, ...values, page: 1 },
    })
  const details = (values: Partial<CallSearch> = {}) =>
    void navigate({
      to: '/llm-calls',
      search: { ...effective, ...values, page: 1 },
    })
  const data = query.data
  const s = data?.summary
  const forbidden =
    query.error instanceof ApiError && [401, 403].includes(query.error.status)
  const choices = { ...metricLabels }
  if (diagnostic) delete (choices as Partial<typeof choices>).points
  const selected = display.selected_members.split(',').filter(Boolean)
  const rankChoices: Record<string, string> = diagnostic
    ? {
        calls: '按调用数',
        input_tokens: '按输入 Token',
        output_tokens: '按输出 Token',
      }
    : {
        calls: '按调用数',
        points: '按已结算积分',
        input_tokens: '按输入 Token',
        output_tokens: '按输出 Token',
      }
  return (
    <PageShell
      title='数据看板'
      action={
        <div className='flex flex-wrap gap-2'>
          <PreferencesDialog scope={scope} current={preferences} />
          <CallFilters
            key={JSON.stringify(effective)}
            search={effective}
            summary
            compact
            onApply={(values) =>
              update({ ...searchFromFilters(values), selected_members: '' })
            }
          />
          <Button
            variant='outline'
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <RefreshCw />
            刷新
          </Button>
          <Button asChild variant='outline'>
            <Link to='/llm-calls' search={effective}>
              调用记录
            </Link>
          </Button>
        </div>
      }
    >
      <Tabs
        value={display.tab}
        onValueChange={(value) => update({ tab: value as Display['tab'] })}
      >
        <TabsList>
          <TabsTrigger value='models'>模型分析</TabsTrigger>
          <TabsTrigger value='flow'>分流</TabsTrigger>
          <TabsTrigger value='members'>成员统计</TabsTrigger>
        </TabsList>
      </Tabs>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='text-sm text-muted-foreground'>
          {timeInZone(effective.from, zone)} 至 {timeInZone(effective.to, zone)}{' '}
          · {zone} · {sources[effective.source]}
        </p>
        <div className='flex w-full flex-wrap gap-2 sm:w-auto'>
          <DashboardSelect
            label='时间粒度'
            value={display.granularity}
            options={{ auto: '自动粒度', hour: '按小时', day: '按天' }}
            onChange={(value) =>
              update({ granularity: value as Display['granularity'] })
            }
          />
          <DashboardSelect
            label='统计指标'
            value={display.metric}
            options={choices}
            onChange={(value) => update({ metric: value as Metric })}
          />
          <DashboardSelect
            label='图表形式'
            value={display.chart}
            options={{ bar: '柱状图', area: '面积图', table: '数据表' }}
            onChange={(value) => update({ chart: value as Display['chart'] })}
          />
        </div>
      </div>
      {!search.timezone &&
        zoneQuery.isSuccess &&
        !zoneQuery.data?.default_timezone && (
          <p className='text-xs text-muted-foreground'>
            UTC（组织未配置默认周策略时区）
          </p>
        )}
      {zoneQuery.isPending && !search.timezone ? (
        <LoadingState />
      ) : zoneQuery.isError && !search.timezone ? (
        <RequestError
          error={zoneQuery.error}
          retry={() => void zoneQuery.refetch()}
        />
      ) : query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError
          error={query.error}
          retry={forbidden ? undefined : () => void query.refetch()}
        />
      ) : (
        data &&
        s && (
          <>
            <MetricGrid label='看板指标'>
              {[
                {
                  name: '逻辑调用',
                  value: String(s.calls),
                  icon: Hash,
                  note: `上游尝试 ${s.attempts} 次`,
                },
                {
                  name: '已结算积分',
                  value: s.settled_points ?? '不适用',
                  icon: Coins,
                  note: '历史比例 · 未结算不计入',
                },
                {
                  name: '输入 / 输出 Token',
                  value: ['input_tokens', 'output_tokens']
                    .map((field) => {
                      const m = s.metrics.find((m) => m.field === field)
                      return m && m.known_calls > 0
                        ? m.sum
                        : s.calls
                          ? '未知 / 不适用'
                          : '0'
                    })
                    .join(' / '),
                  icon: Hash,
                  note: '仅有完整证据的调用小计',
                },
                {
                  name: '调用结果成功率',
                  value: s.calls
                    ? `${(((s.result_counts.success || 0) / s.calls) * 100).toFixed(2)}%`
                    : '—',
                  icon: Activity,
                  note: '全部受理调用为分母',
                },
                {
                  name: '待核对',
                  value: diagnostic
                    ? '不适用'
                    : String(s.settlement_counts.review || 0),
                  icon: CircleHelp,
                  note: '当前筛选内的调用',
                },
              ].map((item) => (
                <Card key={item.name} density='compact' className='min-w-0'>
                  <CardHeader className='pb-2'>
                    <CardTitle size='body' className='flex items-center gap-2'>
                      <item.icon className='size-4' />
                      {item.name}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className='pb-2'>
                    <p className='text-2xl font-semibold break-words tabular-nums'>
                      {item.value}
                    </p>
                    <p className='mt-2 text-xs text-muted-foreground'>
                      {item.note}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </MetricGrid>
            <div className='flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border p-4 text-sm'>
              <span>
                平均耗时{' '}
                {data.performance.average_ms === null
                  ? '—'
                  : `${(data.performance.average_ms / 1000).toFixed(2)}s`}
              </span>
              <span>
                P95{' '}
                {data.performance.p95_ms === null
                  ? '—'
                  : `${(data.performance.p95_ms / 1000).toFixed(2)}s`}
              </span>
              <span>
                耗时样本 {data.performance.samples} / {data.performance.calls}
              </span>
              <span>范围平均 RPM {data.performance.rpm.toFixed(2)}</span>
              <span className='text-muted-foreground'>
                截至 {timeInZone(s.range.as_of, zone)}
              </span>
            </div>
            {!s.calls && (
              <Alert>
                <AlertTitle>该范围没有调用</AlertTitle>
                <AlertDescription>
                  可调整时间与筛选；已确认的空时间桶显示零，未知用量不会补零。
                </AlertDescription>
              </Alert>
            )}
            {display.tab === 'models' && (
              <>
                <TrendChart
                  timeline={data.timeline}
                  metric={display.metric}
                  chart={display.chart}
                  zone={zone}
                  onBucket={(bucket) =>
                    details({ from: bucket.from_time, to: bucket.to_time })
                  }
                />
                <div className='flex flex-wrap gap-2'>
                  <DashboardSelect
                    label='排行指标'
                    value={display.rank}
                    options={rankChoices}
                    onChange={(value) =>
                      update({ rank: value as Display['rank'] })
                    }
                  />
                  <DashboardSelect
                    label='排行数量'
                    value={String(display.top)}
                    options={{ 5: '前5', 10: '前10', 20: '前20', 50: '前50' }}
                    onChange={(value) => update({ top: Number(value) })}
                  />
                </div>
                <Card role='region' aria-label='按操作'>
                  <CardHeader>
                    <CardTitle>按操作</CardTitle>
                  </CardHeader>
                  <CardContent className='flex flex-wrap gap-2'>
                    {s.by_operation.map((item) => (
                      <Button
                        key={item.key}
                        variant='outline'
                        onClick={() => details({ operation: item.key })}
                      >
                        {item.name} · {item.calls} 次 · 看明细
                      </Button>
                    ))}
                  </CardContent>
                </Card>
                <div className='grid min-w-0 gap-4 xl:grid-cols-2'>
                  <Ranking
                    title='模型排行'
                    groups={data.models}
                    metric={display.rank}
                    onDetails={(model_id) => details({ model_id })}
                  />
                  <Card>
                    <CardHeader>
                      <CardTitle>调用结果与结算</CardTitle>
                      <CardDescription>
                        调用结果和费用状态分别统计
                      </CardDescription>
                    </CardHeader>
                    <CardContent className='flex flex-col gap-4'>
                      <div className='flex flex-wrap gap-2'>
                        {Object.entries(results).map(([key, label]) => (
                          <Button
                            key={key}
                            variant='outline'
                            size='sm'
                            onClick={() => details({ result_status: key })}
                          >
                            {label} {s.result_counts[key] || 0}
                          </Button>
                        ))}
                      </div>
                      <div className='flex flex-wrap gap-2'>
                        {Object.entries(settlements).map(([key, label]) => (
                          <Badge key={key} variant='secondary'>
                            {label} {s.settlement_counts[key] || 0}
                          </Badge>
                        ))}
                      </div>
                      {s.amounts_by_currency.map((item) => (
                        <p key={item.currency} className='text-sm'>
                          历史预算结算 {item.amount} {item.currency}
                        </p>
                      ))}
                      <p className='text-xs text-muted-foreground'>
                        币种分别展示；采购估算不代表供应商实际账单。
                      </p>
                    </CardContent>
                  </Card>
                </div>
              </>
            )}
            {display.tab === 'members' && (
              <>
                <div className='flex flex-wrap items-center gap-2'>
                  <DashboardSelect
                    label='排行指标'
                    value={display.rank}
                    options={rankChoices}
                    onChange={(value) =>
                      update({ rank: value as Display['rank'] })
                    }
                  />
                  <DashboardSelect
                    label='排行数量'
                    value={String(display.top)}
                    options={{ 5: '前5', 10: '前10', 20: '前20', 50: '前50' }}
                    onChange={(value) => update({ top: Number(value) })}
                  />
                  <span className='text-sm text-muted-foreground'>
                    显示 {data.members.length} / {data.member_count} 人 · 其他{' '}
                    {data.other_members.calls} 次 /{' '}
                    {data.other_members.settled_points ?? '不适用'} 积分
                  </span>
                </div>
                <Ranking
                  title='成员排行'
                  groups={data.members}
                  metric={display.rank}
                  onDetails={(member_id) => details({ member_id })}
                  onSelect={(id) => {
                    const next = selected.includes(id)
                      ? selected.filter((key) => key !== id)
                      : [...selected, id]
                    if (next.length > 5) {
                      toast.error('最多比较5名成员')
                      return
                    }
                    update({ selected_members: next.join(',') })
                  }}
                />
                {!!selected.length && (
                  <>
                    <div className='flex flex-wrap gap-2'>
                      {selected.map((id) => (
                        <Button
                          key={id}
                          size='sm'
                          variant='outline'
                          onClick={() =>
                            update({
                              selected_members: selected
                                .filter((key) => key !== id)
                                .join(','),
                            })
                          }
                        >
                          {data.member_names?.[id] ??
                            data.members.find((item) => item.key === id)
                              ?.name ??
                            '已选成员'}{' '}
                          ×
                        </Button>
                      ))}
                      <Button
                        variant='link'
                        onClick={() => update({ selected_members: '' })}
                      >
                        清除比较
                      </Button>
                    </div>
                    {Object.keys(data.member_timelines).length > 0 ? (
                      <TrendChart
                        title='所选成员趋势'
                        timeline={data.timeline}
                        metric={display.metric}
                        chart={display.chart}
                        zone={zone}
                        comparisons={Object.fromEntries(
                          Object.entries(data.member_timelines).map(
                            ([id, timeline]) => [
                              id,
                              {
                                name:
                                  data.member_names?.[id] ??
                                  data.members.find((item) => item.key === id)
                                    ?.name ??
                                  '已选成员',
                                timeline,
                              },
                            ]
                          )
                        )}
                      />
                    ) : (
                      <Alert>
                        <AlertDescription>
                          所选成员在当前筛选范围没有调用。
                        </AlertDescription>
                      </Alert>
                    )}
                  </>
                )}
              </>
            )}
            {display.tab === 'flow' && (
              <>
                <div className='flex flex-wrap gap-2'>
                  <DashboardSelect
                    label='路径数量'
                    value={String(display.top)}
                    options={{
                      5: '前5条路径',
                      10: '前10条路径',
                      20: '前20条路径',
                      50: '前50条路径',
                    }}
                    onChange={(value) => update({ top: Number(value) })}
                  />
                  <Button
                    variant='outline'
                    onClick={() => setFlowGraph(!flowGraph)}
                  >
                    {flowGraph ? '仅路径表' : '显示分流图'}
                  </Button>
                  <Badge variant='outline'>
                    按逻辑调用数 · 共 {s.calls} 次
                  </Badge>
                </div>
                <FlowChart
                  paths={data.flow}
                  other={data.other_flow_calls}
                  chart={flowGraph}
                  onDetails={(path) =>
                    details({
                      member_id: path.member_id || '',
                      model_id: path.model_id || '',
                      source: path.source as 'desktop' | 'access_key',
                      channel_id: path.channel_id || '',
                      unknown_channel: !path.channel_id,
                    })
                  }
                />
              </>
            )}
            <Card>
              <CardHeader>
                <CardTitle>未结算预估积分</CardTitle>
                <CardDescription>
                  包含进行中和待核对的历史记录；额度占用以各自受理周期为准
                </CardDescription>
              </CardHeader>
              <CardContent className='flex flex-wrap items-center justify-between gap-3'>
                <span>
                  {s.current_held.applicable
                    ? `${s.current_held.points} 积分`
                    : '管理员诊断不适用'}
                </span>
                {s.current_held.applicable && (
                  <Button
                    variant='outline'
                    onClick={() =>
                      details({
                        from: '',
                        to: '',
                        call_id: '',
                        result_status: '',
                        settlement_status: '',
                        channel_id: '',
                        unknown_channel: false,
                        source: s.current_held.scope?.source || 'member',
                        held: true,
                      })
                    }
                  >
                    查看未结算记录
                  </Button>
                )}
              </CardContent>
            </Card>
            <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
              {s.metrics
                .filter((item) => item.known_calls || item.unknown_calls)
                .map((item) => (
                  <Card key={item.field} density='compact'>
                    <CardHeader>
                      <CardTitle size='body'>
                        {metricLabels[item.field as Metric] || item.field}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className='text-sm'>
                      {item.known_calls
                        ? `确认小计 ${item.sum}`
                        : '暂无完整证据'}{' '}
                      · 完整 {item.known_calls} / 未知 {item.unknown_calls} 笔
                    </CardContent>
                  </Card>
                ))}
            </div>
            <Button asChild variant='link' className='self-start'>
              <Link to='/overview'>返回组织概览</Link>
            </Button>
          </>
        )
      )}
    </PageShell>
  )
}
