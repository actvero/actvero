import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import type { Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { memberOperations, type MyModelSearch } from './search'

type Model = Schema['MemberModelView']
type Operation = Schema['MemberOperationView']

const rateFields: Record<string, string> = {
  input: '输入',
  output: '输出',
  cache_read: '缓存读取',
  cache_write_5m: '缓存写入 5 分钟',
  cache_write_1h: '缓存写入 1 小时',
}
const metricUnits: Record<string, string> = {
  tokens: 'Token',
  characters: '字符',
  search_units: '搜索单位',
  images: '张',
  seconds: '秒',
}
const priceReasons: Record<string, string> = {
  no_price: '未配置预算价，暂不可发送',
  unconfigured: '未配置积分换算，暂不可发送',
  currency_mismatch: '价格币种与积分换算不一致，暂不可发送',
}

function Price({ operation }: { operation: Operation }) {
  if (operation.point_price_status !== 'ready')
    return (
      <p className='text-sm text-muted-foreground'>
        {priceReasons[operation.point_price_status] ?? '积分价暂不可用'}
      </p>
    )
  if (operation.billing_engine === 'newapi')
    return (
      <p className='text-sm text-muted-foreground'>
        按网关实际账单换算积分；用量未确认时保留待核对状态。
      </p>
    )
  const rates = Object.entries(operation.point_rates).filter(
    (entry): entry is [string, string] => entry[1] !== null
  )
  if (!rates.length)
    return <p className='text-sm text-muted-foreground'>积分价暂不可用</p>
  const unit =
    operation.unit === 1
      ? `每${metricUnits[operation.metric] ?? operation.metric}`
      : `每${operation.unit.toLocaleString('zh-CN')} ${metricUnits[operation.metric] ?? operation.metric}`
  return (
    <p className='text-sm break-words'>
      积分价：
      {rates
        .map(([field, value]) => `${rateFields[field] ?? field} ${value}`)
        .join(' · ')}{' '}
      积分 / {unit}
    </p>
  )
}

export function ModelCard({
  model,
  search,
  onExample,
}: {
  model: Model
  search: MyModelSearch
  onExample: (model: Model, operation: Operation, trigger: HTMLElement) => void
}) {
  const operations = search.operation
    ? model.operations.filter((item) => item.kind === search.operation)
    : model.operations
  async function copySlug() {
    try {
      await navigator.clipboard.writeText(model.slug)
      toast.success('已复制公开模型 ID')
    } catch {
      toast.error('复制失败，请选择模型 ID 后手动复制')
    }
  }
  return (
    <Card className='min-w-0'>
      <CardHeader>
        <CardTitle className='break-words'>{model.name}</CardTitle>
        <CardDescription className='break-all'>
          公开模型 ID：{model.slug}
        </CardDescription>
      </CardHeader>
      <CardContent className='grid min-w-0 gap-4'>
        {operations.map((operation) => (
          <section
            key={operation.kind}
            className='grid min-w-0 gap-2 rounded-md border p-3'
          >
            <div className='flex flex-wrap items-center gap-2'>
              <Badge variant='secondary'>
                {memberOperations[operation.kind]}
              </Badge>
              <Badge
                variant={
                  operation.point_price_status === 'ready'
                    ? 'outline'
                    : 'destructive'
                }
              >
                {operation.point_price_status === 'ready'
                  ? '目录可用'
                  : '暂不可发送'}
              </Badge>
            </div>
            <Price operation={operation} />
            <p className='text-sm break-all text-muted-foreground'>
              {operation.endpoint.method} {operation.endpoint.path}
            </p>
            <p className='text-xs text-muted-foreground'>
              输入：{operation.input_modalities.join('、')} · 输出：
              {(operation.output_modalities ?? []).join('、')}
            </p>
            <Button
              type='button'
              size='sm'
              variant='outline'
              className='justify-self-start'
              onClick={(event) =>
                onExample(model, operation, event.currentTarget)
              }
            >
              查看接入示例
            </Button>
          </section>
        ))}
      </CardContent>
      <CardFooter>
        <Button
          type='button'
          variant='ghost'
          size='sm'
          onClick={() => void copySlug()}
        >
          <Copy />
          复制模型 ID
        </Button>
      </CardFooter>
    </Card>
  )
}
