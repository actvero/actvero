import { ExternalLink } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { capabilities } from './model-form'
import { declarationLabels } from './reference-import'
import type { ReferenceModel } from './reference-models'

export function ReferenceDetail({
  model,
  mode,
}: {
  model: ReferenceModel
  mode: 'metadata' | 'price'
}) {
  const fields = [
    ['模型开发方', model.developer_name || '未提供'],
    ['API 供应商', model.provider_name],
    ['模型家族', model.family || '未提供'],
    ['规范模型 ID', model.canonical_model_id || '未提供'],
    ['上下文上限', model.context_window?.toLocaleString() ?? '未知'],
    ['最大输出', model.max_output?.toLocaleString() ?? '未知'],
    ['最大输入', model.max_input?.toLocaleString() ?? '未知'],
    ['温度参数', declarationLabels[model.temperature ?? 'unknown']],
    ['输入类型', model.input_modalities?.join(' / ') || '未提供'],
    ['输出类型', model.output_modalities?.join(' / ') || '未提供'],
    ['发布时间', model.release_date || '未提供'],
    ['资料更新日期', model.last_updated || '未提供'],
    ['知识截止', model.knowledge || '未提供'],
    ['状态', model.status || '未注明'],
  ]
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <div>
        <h3 className='font-semibold break-words'>{model.name}</h3>
        <p className='mt-1 text-sm break-all text-muted-foreground'>
          {model.model_id}
        </p>
      </div>
      <Tabs defaultValue={mode === 'price' ? 'price' : 'metadata'}>
        <TabsList className='w-full'>
          <TabsTrigger value='metadata'>基本资料</TabsTrigger>
          <TabsTrigger value='price'>参考报价</TabsTrigger>
        </TabsList>
        <TabsContent value='metadata' className='flex flex-col gap-4 pt-3'>
          <dl className='grid grid-cols-2 gap-4'>
            {fields.map(([label, value]) => (
              <div key={label} className='min-w-0'>
                <dt className='text-sm text-muted-foreground'>{label}</dt>
                <dd className='mt-1 text-sm break-words'>{value}</dd>
              </div>
            ))}
          </dl>
          <div className='flex flex-wrap gap-2'>
            {capabilities.map(([key, label]) => (
              <Badge key={key} variant='outline'>
                {label} ·{' '}
                {declarationLabels[model.capabilities[key] ?? 'unknown']}
              </Badge>
            ))}
          </div>
          <p className='text-sm text-muted-foreground'>
            公开资料供配置参考，实际能力以所选渠道的测试结果为准。
          </p>
        </TabsContent>
        <TabsContent value='price' className='flex flex-col gap-4 pt-3'>
          <p className='text-sm text-muted-foreground'>
            {model.provider_name} · {model.quote_snapshot?.currency ?? 'USD'} /
            每百万 Token
          </p>
          {model.price ? (
            <dl className='grid grid-cols-2 gap-4'>
              {(
                [
                  ['input', '输入'],
                  ['output', '输出'],
                  ['cache_read', '缓存读取'],
                ] as const
              ).map(([key, label]) => (
                <div key={key}>
                  <dt className='text-sm text-muted-foreground'>{label}</dt>
                  <dd className='mt-1 font-medium tabular-nums'>
                    {model.price?.[key] == null
                      ? '未提供'
                      : `$${model.price[key]}`}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className='text-sm'>未提供可识别的 Token 单价。</p>
          )}
          <Badge variant='secondary' className='self-start'>
            {model.price_importable
              ? '可导入固定单价'
              : '可保存原始报价；生效价格需逐项核对'}
          </Badge>
          {!!model.quote_items?.length && (
            <div className='min-w-0 rounded-md border'>
              <div className='grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b p-2 text-xs font-medium sm:grid-cols-[1fr_1fr_1fr]'>
                <span>报价项目</span>
                <span>原始值</span>
                <span className='col-span-2 sm:col-span-1'>兼容状态</span>
              </div>
              {model.quote_items.map((item) => (
                <div
                  key={item.key}
                  className='grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b p-2 text-xs last:border-0 sm:grid-cols-[1fr_1fr_1fr]'
                >
                  <span className='font-medium break-all'>{item.key}</span>
                  <span className='break-all tabular-nums'>{item.value}</span>
                  <span className='col-span-2 break-words text-muted-foreground sm:col-span-1'>
                    {
                      {
                        compatible: '可用于同维度计价',
                        needs_details: '待补全条件',
                        reference_only: '仅保存参考',
                        invalid: '无有效值',
                      }[item.status]
                    }{' '}
                    · {item.reason}
                  </span>
                </div>
              ))}
            </div>
          )}
          {!!model.price_conditions?.length && (
            <div>
              <h4 className='mb-2 text-sm font-medium'>完整报价条件</h4>
              <ul className='list-disc space-y-2 pl-5 text-sm break-words'>
                {model.price_conditions.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {!!model.price_notes.length && (
            <Alert>
              <AlertDescription>{model.price_notes.join(' ')}</AlertDescription>
            </Alert>
          )}
          <p className='text-sm text-muted-foreground'>
            报价属于该 API
            供应商。采购价格需核对自己的渠道、套餐及折扣；成员预算价格由管理员决定。
          </p>
        </TabsContent>
      </Tabs>
      {model.source_url && (
        <Button asChild variant='link' className='self-start px-0'>
          <a href={model.source_url} target='_blank' rel='noreferrer'>
            供应商文档
            <ExternalLink />
          </a>
        </Button>
      )}
    </div>
  )
}
