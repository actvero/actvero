import { useFormContext, useWatch } from 'react-hook-form'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { routeStates, type ModelValues } from './model-form'
import { RouteParameterFields } from './route-parameter-fields'

export function RoutingFields(props: { names: Record<string, string> }) {
  return (
    <>
      <TimeoutFields />
      <RoutePolicyFields {...props} />
    </>
  )
}

function RoutePolicyFields({ names }: { names: Record<string, string> }) {
  const form = useFormContext<ModelValues>()
  const [kind, mode, fallback, bindings, fixedChannel, fixedUpstream] =
    useWatch({
      control: form.control,
      name: [
        'kind',
        'routing.mode',
        'routing.fallback',
        'bindings',
        'access.channel_id',
        'access.upstream_id',
      ],
    })
  return (
    <Card className='lg:col-span-2'>
      <CardHeader>
        <CardTitle>路由策略</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <div className='grid gap-4 sm:grid-cols-2'>
          <FormField
            control={form.control}
            name='routing.mode'
            render={({ field }) => (
              <FormItem>
                <FormLabel>调度方式</FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='fixed'>固定渠道</SelectItem>
                      {(['chat', 'embedding', 'rerank'] as string[]).includes(
                        kind
                      ) && <SelectItem value='auto'>自动调度</SelectItem>}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          {mode === 'fixed' && (
            <FormField
              control={form.control}
              name='access.channel_id'
              render={() => (
                <FormItem className='flex flex-col gap-2'>
                  <FormLabel htmlFor='fixed-channel'>固定调用渠道</FormLabel>
                  <Select
                    value={
                      fixedChannel ? `${fixedChannel}|${fixedUpstream}` : ''
                    }
                    onValueChange={(value) => {
                      const [channel, upstream] = value.split('|')
                      form.setValue('access.channel_id', channel, {
                        shouldDirty: true,
                        shouldValidate: true,
                      })
                      form.setValue('access.upstream_id', upstream, {
                        shouldDirty: true,
                      })
                    }}
                  >
                    <SelectTrigger id='fixed-channel'>
                      <SelectValue placeholder='选择已启用的渠道关联' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {bindings
                          .filter((binding) => binding.enabled)
                          .map((binding) => (
                            <SelectItem
                              key={`${binding.channel_id}|${binding.upstream_id}`}
                              value={`${binding.channel_id}|${binding.upstream_id}`}
                            >
                              {names[binding.channel_id] ?? '渠道'} /{' '}
                              {binding.upstream_id}
                            </SelectItem>
                          ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                  {!bindings.length && (
                    <p className='text-sm text-muted-foreground'>
                      请先添加渠道关联。
                    </p>
                  )}
                </FormItem>
              )}
            />
          )}
        </div>
        {mode === 'auto' && (
          <>
            {kind !== 'embedding' && (
              <p className='text-sm text-muted-foreground'>
                自动调度使用已启用的渠道关联。测试用于排障，不是开放调用的前置条件。
              </p>
            )}
            <CollapsibleSection title='高级：失败回退与冷却'>
              <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
                <FormField
                  control={form.control}
                  name='routing.fallback'
                  render={({ field }) => (
                    <FormItem className='flex items-center justify-between gap-3'>
                      <FormLabel>失败回退</FormLabel>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {(
                  [
                    ['failure_threshold', '允许失败次数'],
                    ['cooldown_seconds', '冷却时长（秒）'],
                    ...(fallback
                      ? ([['max_attempts', '最多尝试（含首次）']] as const)
                      : []),
                  ] as const
                ).map(([key, label]) => (
                  <FormField
                    key={key}
                    control={form.control}
                    name={`routing.${key}`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{label}</FormLabel>
                        <FormControl>
                          <Input {...field} inputMode='numeric' />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
                {fallback && (
                  <FormField
                    control={form.control}
                    name='routing.retry_uncertain'
                    render={({ field }) => (
                      <FormItem className='flex items-center justify-between gap-3 sm:col-span-2 lg:col-span-3'>
                        <FormLabel>
                          超时／中断后继续尝试（可能重复产生上游费用）
                        </FormLabel>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                <p className='text-sm text-muted-foreground sm:col-span-2 lg:col-span-3'>
                  优先级越大越优先，同级按权重分流。失败切换与冷却由模型执行服务处理。
                </p>
              </div>
            </CollapsibleSection>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function TimeoutFields() {
  const form = useFormContext<ModelValues>()
  return (
    <Card className='lg:col-span-2'>
      <CardHeader>
        <CardTitle>请求时限</CardTitle>
      </CardHeader>
      <CardContent className='grid gap-4 sm:grid-cols-2'>
        {(
          [
            [
              'connect_timeout_seconds',
              '连接超时（秒）',
              '建立供应商连接的最长等待时间，1～120 秒。',
            ],
            [
              'first_response_timeout_seconds',
              '首个响应等待（秒）',
              '流式请求等待首个数据块；非流式请求等待完整结果。3～3600 秒。',
            ],
            [
              'stream_idle_timeout_seconds',
              '输出停滞超时（秒）',
              '仅流式请求生效，每次收到新数据块后重新计时。3～3600 秒。',
            ],
            [
              'total_timeout_seconds',
              '总时长上限（秒）',
              '包含等待、重试和输出的整个请求时长。默认 30 分钟，可设 3～86400 秒。',
            ],
          ] as const
        ).map(([key, label, description]) => (
          <FormField
            key={key}
            control={form.control}
            name={`routing.${key}`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>{label}</FormLabel>
                <FormControl>
                  <Input {...field} inputMode='numeric' />
                </FormControl>
                <FormDescription>{description}</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
      </CardContent>
    </Card>
  )
}

export function BindingRoutingFields({
  index,
  state,
  dirty,
  hideEnabled = false,
}: {
  index: number
  state?: string
  dirty: boolean
  hideEnabled?: boolean
}) {
  const form = useFormContext<ModelValues>()
  const [kind, mode, embeddingSpace] = useWatch({
    control: form.control,
    name: ['kind', 'routing.mode', 'retrieval.embedding_space'],
  })
  return (
    <div className='grid gap-3 sm:grid-cols-2'>
      {kind === 'chat' &&
        (['reasoning_format', 'output_parameter'] as const).map((key) => (
          <FormField
            key={key}
            control={form.control}
            name={`bindings.${index}.chat_options.${key}`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  {key === 'reasoning_format' ? '思考参数格式' : '输出上限参数'}
                </FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      {(key === 'reasoning_format'
                        ? [
                            ['openai', 'OpenAI 强度'],
                            ['thinking', 'thinking 开关'],
                            ['thinking_budget', 'thinking 开关与预算'],
                            ['enable_thinking', 'enable_thinking（千问开关）'],
                          ]
                        : [
                            ['max_completion_tokens', 'max_completion_tokens'],
                            ['max_tokens', 'max_tokens'],
                          ]
                      ).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
      {kind === 'chat' && (
        <div className='sm:col-span-2'>
          <RouteParameterFields index={index} />
        </div>
      )}
      {!hideEnabled && (
        <FormField
          control={form.control}
          name={`bindings.${index}.enabled`}
          render={({ field }) => (
            <FormItem className='flex items-center justify-between gap-3'>
              <FormLabel>启用渠道</FormLabel>
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
      {mode === 'auto' && (
        <>
          <div className='flex items-center gap-2'>
            <Badge variant='outline'>
              {dirty
                ? '保存后检查'
                : (routeStates[state ?? 'unverified'] ?? state)}
            </Badge>
          </div>
          {(['priority', 'weight'] as const).map((key) => (
            <FormField
              key={key}
              control={form.control}
              name={`bindings.${index}.${key}`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {key === 'priority' ? '优先级' : '权重'}
                  </FormLabel>
                  <FormControl>
                    <Input {...field} inputMode='numeric' />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
          {kind === 'embedding' ? (
            <FormField
              control={form.control}
              name={`bindings.${index}.compatibility_key`}
              render={({ field }) => (
                <FormItem className='sm:col-span-2'>
                  <FormLabel>确认向量空间</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder={embeddingSpace || '与模型的向量空间标识一致'}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : null}
          {kind === 'embedding' && (
            <p className='text-sm text-muted-foreground sm:col-span-2'>
              须确认模型版本、预处理和归一化一致；维度相同不代表向量空间相同。
            </p>
          )}
        </>
      )}
    </div>
  )
}
