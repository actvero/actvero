import { useEffect, useRef, useState, type ReactNode } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { JsonEditor } from '@/components/ui/json-editor'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { AudioPreview } from '@/components/audio-preview'
import { RequestError, LoadingState } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { GeneratedImagePreview } from '@/features/model-channels/generated-image-preview'
import { runChatTest, type ChatResult } from './chat-stream'
import {
  kinds,
  routeStates,
  operationModel,
  type OperationKind,
  type Model,
} from './model-form'
import { RetrievalPreview } from './retrieval-preview'

export function ModelTest(props: {
  model: Model
  close: () => void
  restoreFocus: () => void
}) {
  const [kind, setKind] = useState<OperationKind>(
    props.model.operations?.[0]?.kind ?? props.model.kind ?? 'chat'
  )
  return (
    <OperationTest
      {...props}
      key={kind}
      model={operationModel(props.model, kind)}
      operationPicker={(disabled) =>
        props.model.operations &&
        props.model.operations.length > 1 && (
          <Select
            value={kind}
            onValueChange={(value) => setKind(value as OperationKind)}
            disabled={disabled}
          >
            <SelectTrigger aria-label='测试操作'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {props.model.operations.map((op) => (
                  <SelectItem value={op.kind ?? 'chat'} key={op.kind}>
                    {kinds[op.kind ?? 'chat']}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        )
      }
    />
  )
}

function OperationTest({
  model,
  close,
  restoreFocus,
  operationPicker,
}: {
  model: Model
  close: () => void
  restoreFocus: () => void
  operationPicker: (disabled: boolean) => ReactNode
}) {
  const { csrf, organization } = useOrganization()
  const embedding = model.kind === 'embedding'
  const chat = model.kind === 'chat'
  const image = model.kind === 'image_generation'
  const speech = model.kind === 'speech'
  const transcription = model.kind === 'transcription'
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [fileVersion, setFileVersion] = useState(0)
  const [chatResult, setChatResult] = useState<ChatResult | null>(null)
  const schema = z
    .object({
      language: z.string().regex(/^([a-z]{2})?$/, '填写两位语言代码'),
      timestamps: z.boolean(),
      query: z.string(),
      stream: z.boolean(),
      effort: z.string(),
      thinking: z.enum(['omit', 'enabled', 'disabled']),
      extra: z.string().refine((v) => {
        try {
          const parsed = JSON.parse(v || '{}')
          return (
            parsed !== null &&
            typeof parsed === 'object' &&
            !Array.isArray(parsed)
          )
        } catch {
          return false
        }
      }, '填写 JSON 对象'),
      mode: z.enum(['channel', 'route']),
      binding: z.string(),
      texts: z
        .string()
        .refine(
          (v) =>
            transcription || v.split('\n').filter((t) => t.trim()).length > 0,
          '请填写测试内容'
        ),
      count: z
        .string()
        .refine((v) => !v || (/^\d+$/.test(v) && Number(v) >= 1), '填写正整数'),
    })
    .superRefine((v, ctx) => {
      if (v.mode === 'channel' && !v.binding)
        ctx.addIssue({
          code: 'custom',
          path: ['binding'],
          message: '请选择渠道',
        })
      if (
        !embedding &&
        !chat &&
        !image &&
        !speech &&
        !transcription &&
        !v.query.trim()
      )
        ctx.addIssue({
          code: 'custom',
          path: ['query'],
          message: '请填写查询内容',
        })
      if (
        !embedding &&
        !chat &&
        !image &&
        !speech &&
        !transcription &&
        v.count &&
        Number(v.count) > v.texts.split('\n').filter((t) => t.trim()).length
      )
        ctx.addIssue({
          code: 'custom',
          path: ['count'],
          message: '不能大于文档数量',
        })
    })
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      language: '',
      timestamps: false,
      query: '',
      stream: model.capabilities?.streaming === 'supported',
      effort: 'omit',
      thinking: 'omit',
      extra: '',
      texts: '',
      count: '',
      mode: 'channel',
      binding: model.access?.channel_id
        ? `${model.access.channel_id}|${model.access.upstream_id}`
        : model.binding_states?.[0]
          ? `${model.binding_states[0].channel_id}|${model.binding_states[0].upstream_id}`
          : '',
    },
  })
  const [result, setResult] = useState<{
    data:
      | Schema['EmbeddingOutput']
      | Schema['RerankOutput']
      | Schema['ImageOutput']
      | Schema['SpeechOutput']
      | Schema['TranscriptionOutput']
    key: string
  } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState('test')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const path = `/llm/models/${model.id}`
  const logs = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-calls',
      model.id,
      path,
    ],
    queryFn: ({ signal }) =>
      api<Schema['CallView'][]>(
        path + '/calls',
        'GET',
        undefined,
        undefined,
        signal
      ),
    enabled: tab === 'logs',
  })
  const health = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-routes',
      model.id,
      model.version,
      path,
    ],
    queryFn: ({ signal }) =>
      api<Schema['RouteStateView'][]>(
        path + '/routes',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const [mode, selectedBinding] = useWatch({
    control: form.control,
    name: ['mode', 'binding'],
  })
  const draftKey = JSON.stringify([
    useWatch({ control: form.control }),
    fileVersion,
  ])
  async function submit(values: z.infer<typeof schema>) {
    setError(null)
    setResult(null)
    setChatResult(null)
    const texts = values.texts.split('\n').filter((t) => t.trim())
    if (transcription && (!audioFile || audioFile.size > 8_000_000)) {
      setError(new Error('请选择 WAV 音频，最多 8 MB'))
      return
    }
    const upload = new FormData()
    if (transcription && audioFile) {
      upload.set('file', audioFile)
      upload.set('model', model.slug)
      if (values.language) upload.set('language', values.language)
      upload.set('response_format', values.timestamps ? 'verbose_json' : 'json')
    }
    const body = transcription
      ? upload
      : speech
        ? { model: model.slug, input: values.texts }
        : image
          ? { model: model.slug, prompt: values.texts }
          : embedding
            ? {
                model: model.slug,
                input: texts,
                ...(values.count ? { dimensions: Number(values.count) } : {}),
              }
            : {
                model: model.slug,
                query: values.query,
                documents: texts,
                ...(values.count ? { top_n: Number(values.count) } : {}),
              }
    const [channel, upstream] = values.binding.split('|')
    const params =
      values.mode === 'channel'
        ? '?' +
          new URLSearchParams({
            channel_id: channel,
            upstream_id: upstream,
          }).toString()
        : ''
    controller.current = new AbortController()
    try {
      if (chat) {
        const body: Schema['ChatInput'] = {
          ...JSON.parse(values.extra || '{}'),
          model: model.slug,
          n: 1,
          messages: JSON.parse(values.extra || '{}').messages ?? [
            { role: 'user', content: values.texts },
          ],
          stream: values.stream,
          ...(values.count
            ? { max_completion_tokens: Number(values.count) }
            : {}),
          ...(values.effort !== 'omit'
            ? {
                reasoning_effort:
                  values.effort as Schema['ChatInput']['reasoning_effort'],
              }
            : {}),
          ...(values.thinking !== 'omit'
            ? { thinking: { type: values.thinking } }
            : {}),
        }
        await runChatTest(
          path + '/test/chat' + params,
          body,
          csrf,
          controller.current.signal,
          setChatResult
        )
        return
      }
      const data = await api<
        | Schema['EmbeddingOutput']
        | Schema['RerankOutput']
        | Schema['ImageOutput']
        | Schema['SpeechOutput']
        | Schema['TranscriptionOutput']
      >(
        path +
          '/test/' +
          (transcription
            ? 'transcriptions'
            : speech
              ? 'speech'
              : image
                ? 'images'
                : embedding
                  ? 'embeddings'
                  : 'rerank') +
          params,
        'POST',
        body,
        csrf,
        controller.current.signal
      )
      setResult({ data, key: draftKey })
    } catch (e) {
      if (!controller.current.signal.aborted) setError(e)
    } finally {
      void logs.refetch()
      void health.refetch()
    }
  }
  const output = result?.key === draftKey ? result.data : null
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent
        className='max-h-[90dvh] overflow-y-auto sm:max-w-3xl'
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restoreFocus()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {kinds[model.kind ?? 'embedding']}测试 · {model.name}
          </DialogTitle>
          <DialogDescription>
            测试使用已保存的调用渠道，会产生上游费用。
          </DialogDescription>
        </DialogHeader>
        {operationPicker(form.formState.isSubmitting)}
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value='test'>测试</TabsTrigger>
            <TabsTrigger value='logs'>最近调用</TabsTrigger>
          </TabsList>
          <TabsContent value='test' className='flex min-w-0 flex-col gap-4'>
            <Form {...form}>
              <form
                onSubmit={(e) => void form.handleSubmit(submit)(e)}
                className='flex flex-col gap-4'
              >
                <fieldset
                  disabled={form.formState.isSubmitting}
                  className='flex min-w-0 flex-col gap-4'
                >
                  <FormField
                    control={form.control}
                    name='mode'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>测试方式</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                          disabled={form.formState.isSubmitting}
                        >
                          <FormControl>
                            <SelectTrigger className='w-full'>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectGroup>
                              <SelectItem value='channel'>
                                指定渠道（不回退）
                              </SelectItem>
                              <SelectItem value='route'>路由测试</SelectItem>
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  {mode === 'channel' && (
                    <FormField
                      control={form.control}
                      name='binding'
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>测试渠道</FormLabel>
                          <Select
                            value={field.value}
                            onValueChange={field.onChange}
                            disabled={form.formState.isSubmitting}
                          >
                            <FormControl>
                              <SelectTrigger className='w-full'>
                                <SelectValue placeholder='选择渠道' />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectGroup>
                                {(model.binding_states ?? []).map((b) => (
                                  <SelectItem
                                    key={`${b.channel_id}|${b.upstream_id}`}
                                    value={`${b.channel_id}|${b.upstream_id}`}
                                  >
                                    {model.binding_states.find(
                                      (s) => s.channel_id === b.channel_id
                                    )?.channel_name ?? '渠道'}{' '}
                                    / {b.upstream_id}
                                  </SelectItem>
                                ))}
                              </SelectGroup>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}
                  {health.isError && (
                    <RequestError
                      error={health.error}
                      retry={() => void health.refetch()}
                    />
                  )}
                  {mode === 'channel' &&
                    health.data
                      ?.filter(
                        (h) => !h.operation || h.operation === model.kind
                      )
                      ?.filter(
                        (h) =>
                          `${h.channel_id}|${h.upstream_id}` === selectedBinding
                      )
                      .map((h) => (
                        <p
                          key={h.channel_id}
                          className='text-sm text-muted-foreground'
                        >
                          {routeStates[h.state] ?? h.state}
                          {h.tested_at
                            ? ' · 契约测试 ' +
                              new Date(h.tested_at).toLocaleString()
                            : ''}
                        </p>
                      ))}
                  {!embedding &&
                    !chat &&
                    !image &&
                    !speech &&
                    !transcription && (
                      <FormField
                        control={form.control}
                        name='query'
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>查询内容</FormLabel>
                            <FormControl>
                              <Input {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}
                  {transcription ? (
                    <>
                      <div className='flex flex-col gap-2'>
                        <Label htmlFor='transcription-file'>音频文件</Label>
                        <Input
                          id='transcription-file'
                          type='file'
                          accept='.wav,audio/wav'
                          onChange={(event) => {
                            setAudioFile(event.target.files?.[0] ?? null)
                            setFileVersion((v) => v + 1)
                            setError(null)
                          }}
                        />
                        <p className='text-sm text-muted-foreground'>
                          PCM WAV · 最多 8 MB /{' '}
                          {model.transcription?.max_duration_seconds ?? 120} 秒
                        </p>
                      </div>
                      <FormField
                        control={form.control}
                        name='language'
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>语言</FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                placeholder='自动识别（可填 zh、en）'
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      {model.transcription?.timestamps && (
                        <FormField
                          control={form.control}
                          name='timestamps'
                          render={({ field }) => (
                            <FormItem className='flex items-center gap-2'>
                              <FormControl>
                                <Switch
                                  checked={field.value}
                                  onCheckedChange={field.onChange}
                                />
                              </FormControl>
                              <FormLabel>分段时间戳</FormLabel>
                            </FormItem>
                          )}
                        />
                      )}
                    </>
                  ) : (
                    <FormField
                      control={form.control}
                      name='texts'
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            {speech
                              ? '朗读文本'
                              : image
                                ? '图片提示词'
                                : chat
                                  ? '消息内容'
                                  : embedding
                                    ? '输入文本（每行一条）'
                                    : '候选文档（每行一篇）'}
                          </FormLabel>
                          <FormControl>
                            <Textarea {...field} rows={5} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}
                  {!image && !speech && !transcription && (
                    <FormField
                      control={form.control}
                      name='count'
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            {chat
                              ? '最大输出 Token（选填）'
                              : embedding
                                ? '维度（选填）'
                                : '返回数量（选填）'}
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              inputMode='numeric'
                              placeholder='使用模型默认值'
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}
                  {chat && (
                    <>
                      <FormField
                        control={form.control}
                        name='stream'
                        render={({ field }) => (
                          <FormItem className='flex items-center justify-between gap-3'>
                            <FormLabel>流式输出</FormLabel>
                            <FormControl>
                              <Switch
                                disabled={
                                  model.capabilities?.streaming !==
                                    'supported' || form.formState.isSubmitting
                                }
                                checked={field.value}
                                onCheckedChange={field.onChange}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      {model.reasoning_options?.some(
                        (o) => o.type === 'effort'
                      ) && (
                        <FormField
                          control={form.control}
                          name='effort'
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>思考强度</FormLabel>
                              <Select
                                value={field.value}
                                onValueChange={field.onChange}
                              >
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  <SelectGroup>
                                    <SelectItem value='omit'>
                                      上游默认
                                    </SelectItem>
                                    {model.reasoning_options
                                      ?.find((o) => o.type === 'effort')
                                      ?.values.filter((v) => v != null)
                                      .map((v) => (
                                        <SelectItem key={v} value={v!}>
                                          {v}
                                        </SelectItem>
                                      ))}
                                  </SelectGroup>
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}
                      {model.reasoning_options?.some(
                        (o) => o.type === 'toggle'
                      ) && (
                        <FormField
                          control={form.control}
                          name='thinking'
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>思考模式</FormLabel>
                              <Select
                                value={field.value}
                                onValueChange={field.onChange}
                              >
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  <SelectGroup>
                                    <SelectItem value='omit'>
                                      上游默认
                                    </SelectItem>
                                    <SelectItem value='enabled'>
                                      开启
                                    </SelectItem>
                                    <SelectItem value='disabled'>
                                      关闭
                                    </SelectItem>
                                  </SelectGroup>
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}
                      <CollapsibleSection title='更多请求参数'>
                        <FormField
                          control={form.control}
                          name='extra'
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>
                                工具、结构化输出或多轮消息（JSON）
                              </FormLabel>
                              <FormControl>
                                <JsonEditor
                                  {...field}
                                  disabled={form.formState.isSubmitting}
                                  size='compact'
                                  aria-label='更多请求参数 JSON'
                                  placeholder='填写 tools、response_format 或 messages 等参数'
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </CollapsibleSection>
                    </>
                  )}
                  <Button
                    disabled={
                      form.formState.isSubmitting ||
                      !model.binding_states?.length
                    }
                  >
                    {form.formState.isSubmitting ? '请求中…' : '开始测试'}
                  </Button>
                </fieldset>
                {form.formState.isSubmitting && (
                  <Button
                    type='button'
                    variant='outline'
                    onClick={() => controller.current?.abort()}
                  >
                    停止请求
                  </Button>
                )}
                {!model.binding_states?.length && (
                  <p className='text-sm text-muted-foreground'>
                    请先关联并保存渠道。
                  </p>
                )}
              </form>
            </Form>
            {!!error && <RequestError error={error} />}
            {chatResult && (
              <div className='flex min-w-0 flex-col gap-3' role='status'>
                <Textarea
                  aria-label='对话输出'
                  readOnly
                  value={chatResult.content}
                  rows={6}
                />
                {chatResult.reasoning && (
                  <CollapsibleSection title='思考内容'>
                    <Textarea
                      aria-label='思考内容'
                      readOnly
                      value={chatResult.reasoning}
                      rows={4}
                    />
                  </CollapsibleSection>
                )}
                {Object.keys(chatResult.tools).length > 0 && (
                  <CollapsibleSection title='工具调用'>
                    <JsonEditor
                      aria-label='工具调用结果'
                      readOnly
                      size='compact'
                      value={JSON.stringify(chatResult.tools, null, 2)}
                    />
                  </CollapsibleSection>
                )}
                {chatResult.usage != null && (
                  <p className='text-sm break-all text-muted-foreground'>
                    用量：{JSON.stringify(chatResult.usage)}
                  </p>
                )}
              </div>
            )}
            {output && 'data' in output && 'model' in output && (
              <>
                <RetrievalPreview
                  inputTokens={output.usage.prompt_tokens ?? null}
                  vectors={output.data.map((v) => ({
                    index: v.index,
                    dimensions: v.embedding.length,
                    values: v.embedding.slice(0, 8),
                  }))}
                />
              </>
            )}
            {output && 'data' in output && 'id' in output && output.data[0] && (
              <GeneratedImagePreview image={output.data[0]} />
            )}
            {output && 'text' in output && (
              <div className='flex flex-col gap-3'>
                <Textarea
                  aria-label='转写结果'
                  value={output.text}
                  readOnly
                  rows={6}
                />
                {output.segments && (
                  <CollapsibleSection title='分段时间戳'>
                    {output.segments.map((s, i) => (
                      <p key={i} className='text-sm break-words'>
                        {s.start.toFixed(2)} – {s.end.toFixed(2)} 秒 · {s.text}
                      </p>
                    ))}
                  </CollapsibleSection>
                )}
              </div>
            )}
            {output && 'audio' in output && (
              <AudioPreview audio={output.audio} />
            )}
            {output && 'results' in output && (
              <RetrievalPreview ranks={output.results} />
            )}
          </TabsContent>
          <TabsContent value='logs' className='flex min-w-0 flex-col gap-4'>
            <Button
              variant='outline'
              onClick={() => void logs.refetch()}
              disabled={logs.isFetching}
            >
              刷新记录
            </Button>
            {logs.isPending ? (
              <LoadingState />
            ) : logs.error ? (
              <RequestError
                error={logs.error}
                retry={() => void logs.refetch()}
              />
            ) : !logs.data?.length ? (
              <p className='text-sm text-muted-foreground'>暂无调用记录</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间／来源</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>耗时</TableHead>
                    <TableHead>最终尝试用量</TableHead>
                    <TableHead>最终尝试采购试算</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.data.map((row) => {
                    const estimate = row.estimates.procurement as {
                      status: string
                      amount?: string
                      currency?: string
                      metric?: string
                    }
                    return (
                      <TableRow key={row.id}>
                        <TableCell>
                          {new Date(row.created_at).toLocaleString()}
                          <br />
                          {row.source === 'access_key'
                            ? '访问密钥'
                            : row.source === 'desktop'
                              ? '客户端'
                              : '管理员测试'}
                        </TableCell>
                        <TableCell>
                          {row.status === 'succeeded'
                            ? '成功'
                            : row.status === 'failed'
                              ? '失败'
                              : '处理中／结果未确认'}
                          {row.error_code && <p>{row.error_code}</p>}
                          {row.termination_code && (
                            <p>{row.termination_code}</p>
                          )}
                          {!!row.attempts?.length && (
                            <CollapsibleSection
                              title={`${row.attempts.length} 次尝试`}
                            >
                              <div className='flex flex-col gap-3'>
                                {row.attempts.map((a) => {
                                  const cost = a.estimates.procurement as
                                    | {
                                        status?: string
                                        currency?: string
                                        amount?: string
                                      }
                                    | undefined
                                  return (
                                    <div
                                      key={a.number}
                                      className='space-y-1 text-sm'
                                    >
                                      <p>
                                        #{a.number} {a.channel_name} /{' '}
                                        {a.upstream_id}
                                      </p>
                                      <p>
                                        {a.status === 'succeeded'
                                          ? '成功'
                                          : a.status === 'failed'
                                            ? '失败'
                                            : '结果未确认'}{' '}
                                        · {a.duration_ms ?? '—'} ms
                                        {a.upstream_status
                                          ? ` · HTTP ${a.upstream_status}`
                                          : ''}
                                      </p>
                                      {a.error_code && <p>{a.error_code}</p>}
                                      {a.uncertain && (
                                        <p>执行结果未确认，可能产生费用</p>
                                      )}
                                      {a.retry_reason && (
                                        <p>回退原因：{a.retry_reason}</p>
                                      )}
                                      <p>
                                        {row.kind === 'transcription'
                                          ? '音频毫秒：'
                                          : row.kind === 'speech'
                                            ? '输入字符：'
                                            : 'Token：'}
                                        {String(
                                          (row.kind === 'transcription'
                                            ? a.usage.audio_duration_ms
                                            : row.kind === 'speech'
                                              ? a.usage.input_characters
                                              : a.usage.input_tokens) ?? '未知'
                                        )}{' '}
                                        · 采购：
                                        {cost?.status === 'estimate'
                                          ? `${cost.currency} ${cost.amount}`
                                          : '费用未知'}
                                      </p>
                                    </div>
                                  )
                                })}
                              </div>
                            </CollapsibleSection>
                          )}
                        </TableCell>
                        <TableCell>{row.duration_ms ?? '—'} ms</TableCell>
                        <TableCell>
                          {row.kind === 'transcription' ? (
                            <>
                              音频：
                              {typeof row.usage.audio_duration_ms === 'number'
                                ? `${row.usage.audio_duration_ms / 1000} 秒`
                                : '未知'}
                              <br />
                              平台时长计价
                            </>
                          ) : row.kind === 'speech' ? (
                            <>
                              输入字符：
                              {String(row.usage.input_characters ?? '未知')}
                              <br />
                              平台字符计价 · 上游用量未知
                            </>
                          ) : (
                            <>
                              Token：{String(row.usage.input_tokens ?? '未知')}
                            </>
                          )}
                          {row.kind === 'rerank' && (
                            <>
                              <br />
                              搜索单位：
                              {String(row.usage.search_units ?? '未知')}
                            </>
                          )}
                        </TableCell>
                        <TableCell>
                          {estimate?.status === 'estimate'
                            ? `${estimate.currency} ${estimate.amount}`
                            : '未计价'}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
