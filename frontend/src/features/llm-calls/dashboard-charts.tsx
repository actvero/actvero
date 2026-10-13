import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Sankey,
  Rectangle,
} from 'recharts'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from '@/components/ui/chart'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { metricLabels, type Metric } from './dashboard-search'
import { sources } from './filters'
import { timeInZone } from './time'

type Group = Schema['DashboardGroup']
type Bucket = Schema['TimeBucket']
type Path = Schema['FlowPath']
function exactValue(group: Group, metric: Metric) {
  if (metric === 'calls') return String(group.calls)
  if (metric === 'points') return group.settled_points
  const quantity = (group.metrics ?? []).find((item) => item.field === metric)
  return quantity && (quantity.known_calls > 0 || group.calls === 0)
    ? quantity.sum
    : null
}
function coverage(group: Group, metric: Metric) {
  if (metric === 'calls') return '逻辑调用'
  if (metric === 'points') return '仅已结算；待核对不计入'
  const quantity = (group.metrics ?? []).find((item) => item.field === metric)
  if (
    !quantity ||
    (!quantity.known_calls && !quantity.unknown_calls && group.calls)
  )
    return '不适用'
  return `完整证据 ${quantity.known_calls} 笔 · 未知 ${quantity.unknown_calls} 笔`
}
export function TrendChart({
  title = '用量趋势',
  timeline,
  metric,
  chart,
  zone,
  onBucket,
  comparisons = {},
}: {
  title?: string
  timeline: Bucket[]
  metric: Metric
  chart: 'bar' | 'area' | 'table'
  zone: string
  onBucket?: (bucket: Bucket) => void
  comparisons?: Record<string, { name: string; timeline: Bucket[] }>
}) {
  const keys = Object.keys(comparisons)
  const config = keys.length
    ? Object.fromEntries(
        keys.map((key, index) => [
          key,
          { label: comparisons[key].name, color: `var(--chart-${index + 1})` },
        ])
      )
    : { value: { label: metricLabels[metric], color: 'var(--chart-1)' } }
  const rows = timeline.map((bucket, index) => ({
    name: timeInZone(bucket.from_time, zone),
    value:
      exactValue(bucket, metric) === null
        ? null
        : Number(exactValue(bucket, metric)),
    ...Object.fromEntries(
      keys.map((key) => [
        key,
        exactValue(comparisons[key].timeline[index], metric) === null
          ? null
          : Number(exactValue(comparisons[key].timeline[index], metric)),
      ])
    ),
  }))
  const chartKeys = keys.length ? keys : ['value']
  const series = chartKeys.map((key) =>
    chart === 'area' ? (
      <Area
        key={key}
        dataKey={key}
        type='linear'
        stroke={`var(--color-${key})`}
        fill={`var(--color-${key})`}
        fillOpacity={0.12}
        connectNulls={false}
        isAnimationActive={false}
      />
    ) : (
      <Bar
        key={key}
        dataKey={key}
        fill={`var(--color-${key})`}
        radius={3}
        isAnimationActive={false}
      />
    )
  )
  const axes = (
    <>
      <CartesianGrid vertical={false} />
      <XAxis
        dataKey='name'
        tickLine={false}
        axisLine={false}
        minTickGap={45}
        tickFormatter={(value) => String(value).replace(/^\d{4}\//, '')}
      />
      <YAxis width={48} tickLine={false} axisLine={false} />
      <ChartTooltip content={<ChartTooltipContent />} />
      {keys.length > 0 && <ChartLegend content={<ChartLegendContent />} />}
    </>
  )
  const unknown =
    metric !== 'calls' && metric !== 'points'
      ? timeline.reduce(
          (sum, item) =>
            sum +
            ((item.metrics ?? []).find((m) => m.field === metric)
              ?.unknown_calls ?? 0),
          0
        )
      : 0
  return (
    <Card className='min-w-0'>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          {metricLabels[metric]} · 按受理时间 ·{' '}
          {unknown
            ? `未知用量 ${unknown} 笔；曲线只展示确认小计`
            : '同一筛选范围；费用取历史结算比例'}
        </CardDescription>
      </CardHeader>
      <CardContent className='min-w-0'>
        {chart === 'table' ? (
          <div className='max-h-96 overflow-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间桶</TableHead>
                  <TableHead>{metricLabels[metric]}</TableHead>
                  <TableHead>证据/口径</TableHead>
                  {keys.map((key) => (
                    <TableHead key={key}>{comparisons[key].name}</TableHead>
                  ))}
                  {onBucket && <TableHead>明细</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {timeline.map((bucket, index) => (
                  <TableRow key={bucket.from_time}>
                    <TableCell className='whitespace-nowrap'>
                      {timeInZone(bucket.from_time, zone)}
                    </TableCell>
                    <TableCell>
                      {exactValue(bucket, metric) ?? '未知 / 不适用'}
                    </TableCell>
                    <TableCell className='min-w-40'>
                      {coverage(bucket, metric)}
                    </TableCell>
                    {keys.map((key) => (
                      <TableCell key={key}>
                        {exactValue(comparisons[key].timeline[index], metric) ??
                          '未知 / 不适用'}
                      </TableCell>
                    ))}
                    {onBucket && (
                      <TableCell>
                        <Button
                          variant='link'
                          size='sm'
                          onClick={() => onBucket(bucket)}
                        >
                          看明细
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <ChartContainer config={config} className='h-72 w-full'>
            {chart === 'area' ? (
              <AreaChart accessibilityLayer data={rows}>
                {axes}
                {series}
              </AreaChart>
            ) : (
              <BarChart accessibilityLayer data={rows}>
                {axes}
                {series}
              </BarChart>
            )}
          </ChartContainer>
        )}
        {!!keys.length && (
          <div className='mt-3 flex flex-wrap gap-3 text-sm'>
            {keys.map((key) => (
              <span key={key}>{comparisons[key].name}</span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
export function Ranking({
  title,
  groups,
  metric,
  onSelect,
  onDetails,
}: {
  title: string
  groups: Group[]
  metric: Metric
  onSelect?: (key: string) => void
  onDetails: (key: string) => void
}) {
  return (
    <Card className='min-w-0'>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          {metricLabels[metric]} · 按稳定编号分组
        </CardDescription>
      </CardHeader>
      <CardContent className='min-w-0'>
        {!groups.length ? (
          <p className='text-sm text-muted-foreground'>该范围暂无记录</p>
        ) : (
          <>
            <ChartContainer
              config={{
                value: { label: metricLabels[metric], color: 'var(--chart-2)' },
              }}
              className='w-full'
              style={{ height: Math.max(150, groups.length * 34) }}
            >
              <BarChart
                accessibilityLayer
                layout='vertical'
                data={groups.map((group) => ({
                  name: group.name,
                  value:
                    exactValue(group, metric) === null
                      ? null
                      : Number(exactValue(group, metric)),
                }))}
                margin={{ left: 0, right: 12 }}
              >
                <XAxis type='number' hide />
                <YAxis
                  type='category'
                  dataKey='name'
                  width={95}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(value) =>
                    String(value).length > 10
                      ? `${String(value).slice(0, 10)}…`
                      : String(value)
                  }
                />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar
                  dataKey='value'
                  fill='var(--color-value)'
                  radius={3}
                  isAnimationActive={false}
                />
              </BarChart>
            </ChartContainer>
            <div className='max-h-96 overflow-auto'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>{metricLabels[metric]}</TableHead>
                    <TableHead>调用 / 待核对</TableHead>
                    <TableHead>证据</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groups.map((group) => (
                    <TableRow key={group.key}>
                      <TableCell className='min-w-28 break-words'>
                        {group.name}
                      </TableCell>
                      <TableCell>
                        {exactValue(group, metric) ?? '未知 / 不适用'}
                      </TableCell>
                      <TableCell>
                        {group.calls} / {group.review}
                      </TableCell>
                      <TableCell className='min-w-36'>
                        {coverage(group, metric)}
                      </TableCell>
                      <TableCell>
                        <div className='flex gap-1'>
                          {onSelect && (
                            <Button
                              size='sm'
                              variant='outline'
                              disabled={group.key === 'unknown'}
                              onClick={() => onSelect(group.key)}
                            >
                              比较趋势
                            </Button>
                          )}
                          <Button
                            size='sm'
                            variant='link'
                            disabled={group.key === 'unknown'}
                            onClick={() => onDetails(group.key)}
                          >
                            看明细
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
export function FlowChart({
  paths,
  other,
  chart,
  onDetails,
}: {
  paths: Path[]
  other: number
  chart: boolean
  onDetails: (path: Path) => void
}) {
  const nodes: { name: string }[] = []
  const index = new Map<string, number>()
  const links = new Map<
    string,
    { source: number; target: number; value: number }
  >()
  function node(key: string, name: string) {
    if (!index.has(key)) {
      index.set(key, nodes.length)
      nodes.push({ name })
    }
    return index.get(key)!
  }
  for (const path of paths) {
    const stages = [
      node(`member:${path.member_id}`, path.member_name),
      node(
        `source:${path.source}`,
        sources[path.source as keyof typeof sources] || '管理员诊断'
      ),
      node(`model:${path.model_id}`, path.model_name),
      node(`channel:${path.channel_id}`, path.channel_name),
    ]
    for (let i = 0; i < 3; i++) {
      const key = `${stages[i]}-${stages[i + 1]}`
      const link = links.get(key) ?? {
        source: stages[i],
        target: stages[i + 1],
        value: 0,
      }
      link.value += path.calls
      links.set(key, link)
    }
  }
  return (
    <Card className='min-w-0'>
      <CardHeader>
        <CardTitle>调用分流</CardTitle>
        <CardDescription>
          成员 → 来源 → 模型 → 最终渠道 · 每次逻辑调用计一次；未确认归属单列
        </CardDescription>
      </CardHeader>
      <CardContent className='min-w-0'>
        {chart && paths.length > 0 && (
          <div className='hidden max-h-96 overflow-y-auto md:block'>
            <ChartContainer
              config={{ calls: { label: '调用数', color: 'var(--chart-1)' } }}
              className='w-full'
              style={{ height: Math.max(384, nodes.length * 24 + 96) }}
            >
              <Sankey
                data={{ nodes, links: [...links.values()] }}
                margin={{ top: 24, bottom: 24, left: 100, right: 125 }}
                nodePadding={24}
                nodeWidth={8}
                iterations={32}
                link={{ stroke: 'var(--chart-1)', strokeOpacity: 0.3 }}
                node={({ x, y, width, height, payload }) => (
                  <g>
                    <Rectangle
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill='var(--chart-1)'
                    />
                    <text
                      x={x < 200 ? x - 8 : x + width + 8}
                      y={y + height / 2}
                      textAnchor={x < 200 ? 'end' : 'start'}
                      dominantBaseline='middle'
                      fill='var(--foreground)'
                      fontSize={12}
                    >
                      {String(payload.name).slice(0, 14)}
                    </text>
                  </g>
                )}
              />
            </ChartContainer>
          </div>
        )}
        {other > 0 && (
          <p className='mb-3 text-sm text-muted-foreground'>
            当前显示前 {paths.length} 条路径；其他路径 {other}{' '}
            次，未混入可见图。总数包含其他路径。
          </p>
        )}
        <div className='overflow-auto'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>成员</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>模型</TableHead>
                <TableHead>渠道</TableHead>
                <TableHead>调用</TableHead>
                <TableHead>明细</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paths.map((path, i) => (
                <TableRow key={i}>
                  <TableCell className='min-w-24'>{path.member_name}</TableCell>
                  <TableCell className='min-w-24'>
                    {sources[path.source as keyof typeof sources] ||
                      '管理员诊断'}
                  </TableCell>
                  <TableCell className='min-w-24'>{path.model_name}</TableCell>
                  <TableCell className='min-w-24'>
                    {path.channel_name}
                  </TableCell>
                  <TableCell>{path.calls}</TableCell>
                  <TableCell>
                    <Button
                      size='sm'
                      variant='link'
                      disabled={
                        !path.member_id ||
                        !path.model_id ||
                        !['access_key', 'desktop'].includes(path.source)
                      }
                      onClick={() => onDetails(path)}
                    >
                      看明细
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {!paths.length && (
          <p className='py-4 text-sm text-muted-foreground'>
            该范围暂无调用路径
          </p>
        )}
      </CardContent>
    </Card>
  )
}
