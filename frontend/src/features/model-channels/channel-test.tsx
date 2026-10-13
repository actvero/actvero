import { useEffect, useRef, useState } from 'react'
import type { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, ApiError } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
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
import { Textarea } from '@/components/ui/textarea'
import { AudioPreview } from '@/components/audio-preview'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { RetrievalPreview } from '@/features/model-catalog/retrieval-preview'
import { channelPath } from './api'
import { ChannelTestHistory } from './channel-test-history'
import { DiagnosticEvidence } from './diagnostic-evidence'
import { diagnosticFormSchema as schema, sampleFor } from './diagnostic-form'
import {
  diagnosticBody,
  endpointFor,
  initialDiagnosticSelection,
  type DiagnosticLookup,
  type DiagnosticView,
} from './diagnostic-request'
import {
  DiagnosticStreamError,
  runDiagnosticStream,
  type StreamProgress,
} from './diagnostic-stream'
import { GeneratedImagePreview } from './generated-image-preview'
import { ImageTestOptions } from './image-test-options'
import type { Detail } from './shared'
import {
  meterLabel,
  operationLabels,
  type TestOperation,
} from './test-operations'

export function ChannelTest({
  channel,
  operations = ['chat'],
  busy,
  setBusy,
  historyOpen = false,
  showHistory = true,
  onFinished,
  initialModelId,
  initialOperation,
  initialBindingId,
}: {
  channel: Detail
  operations?: TestOperation[]
  busy: boolean
  setBusy: (value: boolean) => void
  historyOpen?: boolean
  showHistory?: boolean
  onFinished?: () => void
  initialModelId?: string
  initialOperation?: TestOperation
  initialBindingId?: string
}) {
  const { csrf } = useOrganization()
  const [result, setResult] = useState<DiagnosticView | null>(null)
  const [lookup, setLookup] = useState<DiagnosticLookup | null>(null)
  const [requestId, setRequestId] = useState('')
  const [unknown, setUnknown] = useState(false)
  const [checking, setChecking] = useState(false)
  const [lookupMissing, setLookupMissing] = useState(false)
  const [sending, setSending] = useState(false)
  const [certify, setCertify] = useState(!!initialBindingId)
  const [bindingId, setBindingId] = useState(initialBindingId ?? '')
  const [tested, setTested] = useState('')
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [permissionLost, setPermissionLost] = useState(false)
  const [stream, setStream] = useState(
    !initialBindingId &&
      !initialModelId &&
      !initialOperation &&
      channel.test_defaults_status?.valid === true &&
      channel.test_defaults?.operation === 'chat' &&
      channel.test_defaults.stream === true
  )
  const [streamProgress, setStreamProgress] = useState<StreamProgress | null>(
    null
  )
  const [streamTerminalStatus, setStreamTerminalStatus] = useState<
    'success' | 'failure' | 'unconfirmed' | null
  >(null)
  const [conflictVersion, setConflictVersion] = useState<number | null>(null)
  const running = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const lookupController = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      controller.current?.abort()
      lookupController.current?.abort()
      setBusy(false)
    }
  }, [setBusy])
  const initialBinding = channel.binding_references?.find(
    (item) => item.binding_id === initialBindingId
  )
  const starting = initialBinding
    ? initialDiagnosticSelection(
        channel,
        operations,
        initialBinding.upstream_model_id,
        initialBinding.operation as TestOperation
      )
    : initialDiagnosticSelection(
        channel,
        operations,
        initialModelId,
        initialOperation
      )
  const startingOperation = starting.operation
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      id: starting.id,
      operation: startingOperation,
      ...sampleFor(startingOperation),
      voice: '',
      size: '',
      quality: '',
    },
  })
  const operation = useWatch({ control: form.control, name: 'operation' })
  const upstreamId = useWatch({ control: form.control, name: 'id' })
  const bindings = (channel.binding_references ?? []).filter(
    (item) =>
      item.operation === operation && item.upstream_model_id === upstreamId
  )
  const selectedBinding = bindings.find((item) => item.binding_id === bindingId)
  const staleVersion = conflictVersion === channel.version
  const disabled = busy || channel.archived || permissionLost
  function changeOperation(value: TestOperation) {
    form.setValue('operation', value)
    const sample = sampleFor(value)
    form.setValue('texts', sample.texts)
    form.setValue('query', sample.query)
    form.setValue('count', sample.count)
    form.clearErrors()
    setResult(null)
    setLookup(null)
    setLookupMissing(false)
    setBindingId('')
    setStream(false)
    setStreamProgress(null)
    setStreamTerminalStatus(null)
    setError(null)
  }
  async function submit(values: z.infer<typeof schema>) {
    if (
      running.current ||
      busy ||
      unknown ||
      staleVersion ||
      permissionLost ||
      channel.archived ||
      !values.operation ||
      !operations.includes(values.operation)
    )
      return
    if (
      certify &&
      (!selectedBinding ||
        !('model_version' in selectedBinding) ||
        typeof selectedBinding.model_version !== 'number')
    ) {
      setError(new Error('请明确选择有当前模型版本的绑定，再认证健康。'))
      return
    }
    running.current = true
    setSending(true)
    setBusy(true)
    setError(null)
    setResult(null)
    setStreamProgress(null)
    setStreamTerminalStatus(null)
    setLookup(null)
    setLookupMissing(false)
    setTested(`${values.id} · ${operationLabels[values.operation]}`)
    const id = crypto.randomUUID()
    const abort = new AbortController()
    controller.current = abort
    setRequestId(id)
    try {
      const body = diagnosticBody(
        channel,
        values,
        id,
        certify ? selectedBinding : null,
        values.operation === 'chat' && stream
      )
      if (values.operation === 'chat' && stream) {
        const terminal = await runDiagnosticStream(
          channelPath(channel.id) + '/diagnostics',
          body,
          csrf,
          id,
          abort.signal,
          (progress) => {
            if (mounted.current) setStreamProgress(progress)
          }
        )
        if (!mounted.current) return
        setResult(terminal.result)
        setStreamTerminalStatus(terminal.status)
        if (terminal.status === 'unconfirmed') setUnknown(true)
      } else {
        const response = await api<DiagnosticView>(
          channelPath(channel.id) + '/diagnostics',
          'POST',
          body,
          csrf,
          abort.signal
        )
        if (!mounted.current) return
        setResult(response)
      }
      onFinished?.()
    } catch (e) {
      if (!mounted.current) return
      setError(
        e instanceof DOMException && e.name === 'AbortError'
          ? new Error('已停止等待；请求可能已发送，请按请求号回查。')
          : (e instanceof ApiError || e instanceof DiagnosticStreamError) &&
              e.status === 409
            ? new Error(
                `${e.message}。请按请求号回查，并刷新渠道后再发起新测试。`
              )
            : e
      )
      if (
        (e instanceof ApiError || e instanceof DiagnosticStreamError) &&
        (e.status === 401 || e.status === 403)
      ) {
        setPermissionLost(true)
        setResult(null)
        setLookup(null)
        setStreamProgress(null)
      } else if (
        e instanceof DiagnosticStreamError ||
        !(e instanceof ApiError) ||
        e.status === 409 ||
        e.status >= 500
      )
        setUnknown(true)
      if (
        (e instanceof ApiError || e instanceof DiagnosticStreamError) &&
        e.status === 409
      )
        setConflictVersion(channel.version)
    } finally {
      controller.current = null
      running.current = false
      if (mounted.current) {
        setSending(false)
        setBusy(false)
        setRevision((value) => value + 1)
      }
    }
  }
  async function findRecord() {
    if (!requestId || checking || permissionLost) return
    setChecking(true)
    setError(null)
    const abort = new AbortController()
    lookupController.current = abort
    try {
      const found = await api<DiagnosticLookup>(
        `/llm/diagnostics/${requestId}`,
        'GET',
        undefined,
        undefined,
        abort.signal
      )
      if (!mounted.current) return
      if (found.channel_id !== channel.id)
        throw new Error('回查结果不属于当前渠道')
      setLookup(found)
      setUnknown(true)
      setLookupMissing(false)
      setRevision((value) => value + 1)
    } catch (e) {
      if (!mounted.current) return
      setError(
        e instanceof ApiError && e.status === 404
          ? new Error('暂未查到本次记录。可稍后再次回查，或明确发起新测试。')
          : e
      )
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setPermissionLost(true)
        setResult(null)
        setLookup(null)
        setStreamProgress(null)
      }
      if (e instanceof ApiError && e.status === 404) setLookupMissing(true)
    } finally {
      lookupController.current = null
      if (mounted.current) setChecking(false)
    }
  }
  const unavailable = !channel.models.length || !operations.length
  if (unavailable && !requestId)
    return (
      <div className='flex flex-col gap-4'>
        <p className='text-sm text-muted-foreground'>
          {!channel.models.length
            ? '请先添加上游模型。'
            : '此供应商尚未接入调用测试。'}
        </p>
        {showHistory && (
          <ChannelTestHistory
            id={channel.id}
            revision={revision}
            busy={busy}
            initialOpen={historyOpen}
          />
        )}
      </div>
    )
  return (
    <div className='flex min-w-0 flex-col gap-5'>
      {channel.test_defaults && !channel.test_defaults_status?.valid && (
        <p className='text-sm text-muted-foreground'>
          保存的默认测试项已失效，请明确重新选择模型和测试接口。
        </p>
      )}
      <p className='text-sm text-muted-foreground'>
        单项诊断仅使用平台已接入的接口；对话可选择流式。测试可能产生上游费用，不扣成员额度。
      </p>
      <Form {...form}>
        <form
          onSubmit={(event) => void form.handleSubmit(submit)(event)}
          onChange={() => {
            setResult(null)
            setError(null)
          }}
          className='flex flex-col gap-4'
        >
          <fieldset disabled={disabled} className='flex min-w-0 flex-col gap-4'>
            <FormField
              control={form.control}
              name='id'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>测试模型</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={(value) => {
                      field.onChange(value)
                      setBindingId('')
                      setStream(false)
                      setStreamProgress(null)
                      setStreamTerminalStatus(null)
                      setResult(null)
                      setLookup(null)
                      setError(null)
                    }}
                    disabled={disabled}
                  >
                    <FormControl>
                      <SelectTrigger className='w-full min-w-0'>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectGroup>
                        {channel.models.map((model) => (
                          <SelectItem key={model.id} value={model.id}>
                            {model.id}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            {operations.length > 1 || !operation ? (
              <FormField
                control={form.control}
                name='operation'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>测试接口</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={(value) =>
                        changeOperation(value as TestOperation)
                      }
                      disabled={disabled}
                    >
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue placeholder='请选择测试接口' />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          {operations.map((value) => (
                            <SelectItem key={value} value={value}>
                              {operationLabels[value]}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <p className='text-sm'>{operationLabels[operations[0]]}测试</p>
            )}
            {!!operation && (
              <p className='text-sm text-muted-foreground'>
                调用接口：{endpointFor[operation]} ·{' '}
                {operation === 'chat' && stream ? '流式' : '非流式'}
              </p>
            )}
            {operation === 'chat' && (
              <div className='flex items-center gap-3'>
                <Switch
                  id='diagnostic-stream'
                  checked={stream}
                  onCheckedChange={(checked) => {
                    setStream(checked)
                    setResult(null)
                    setStreamProgress(null)
                    setStreamTerminalStatus(null)
                  }}
                  disabled={disabled}
                />
                <label htmlFor='diagnostic-stream' className='text-sm'>
                  流式接收对话
                </label>
              </div>
            )}
            <div className='flex min-w-0 flex-col gap-2'>
              <p className='text-sm font-medium'>测试方式</p>
              <Select
                value={certify ? 'certify' : 'ordinary'}
                onValueChange={(value) => {
                  setCertify(value === 'certify')
                  setStream(false)
                  setResult(null)
                  setLookup(null)
                }}
                disabled={disabled}
              >
                <SelectTrigger className='w-full' aria-label='测试方式'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='ordinary'>
                    普通诊断（不更新绑定健康）
                  </SelectItem>
                  <SelectItem value='certify' disabled={!bindings.length}>
                    指定绑定健康认证
                  </SelectItem>
                </SelectContent>
              </Select>
              {certify && (
                <>
                  <p className='text-sm text-muted-foreground'>
                    只认证下方明确选择的模型绑定；不改变渠道开关、模型开关或成员授权。
                  </p>
                  <Select
                    value={
                      bindings.some((item) => item.binding_id === bindingId)
                        ? bindingId
                        : ''
                    }
                    onValueChange={(value) => {
                      setBindingId(value)
                      setStream(false)
                    }}
                    disabled={disabled}
                  >
                    <SelectTrigger
                      className='w-full min-w-0'
                      aria-label='认证绑定'
                    >
                      <SelectValue placeholder='请选择要认证的绑定' />
                    </SelectTrigger>
                    <SelectContent>
                      {bindings.map((item) => (
                        <SelectItem
                          key={item.binding_id}
                          value={item.binding_id}
                        >
                          {item.model_name} ·{' '}
                          {operationLabels[operation as TestOperation]} ·{' '}
                          {item.upstream_model_id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
            </div>
            {!!operation && (
              <>
                {operation === 'rerank' && (
                  <FormField
                    control={form.control}
                    name='query'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>查询内容</FormLabel>
                        <FormControl>
                          <Input {...field} maxLength={2000} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                <FormField
                  control={form.control}
                  name='texts'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        {operation === 'speech'
                          ? '朗读文本'
                          : operation === 'image_generation'
                            ? '图片描述'
                            : operation === 'chat'
                              ? '测试内容'
                              : operation === 'embedding'
                                ? '输入文本（每行一条）'
                                : '候选文档（每行一篇）'}
                      </FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          maxLength={
                            operation === 'speech'
                              ? 1000
                              : operation === 'chat' ||
                                  operation === 'image_generation'
                                ? 2000
                                : 16007
                          }
                          rows={3}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {operation === 'speech' ? (
                  <>
                    <FormField
                      control={form.control}
                      name='voice'
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>音色</FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              placeholder='上游音色 ID，例如 alloy'
                              maxLength={100}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <p className='text-sm text-muted-foreground'>
                      输出格式：WAV
                    </p>
                  </>
                ) : operation === 'image_generation' ? (
                  <ImageTestOptions disabled={disabled} />
                ) : (
                  <FormField
                    control={form.control}
                    name='count'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          {operation === 'chat'
                            ? '最大输出 Token'
                            : operation === 'embedding'
                              ? '维度（选填）'
                              : '返回数量（选填）'}
                        </FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            inputMode='numeric'
                            placeholder={
                              operation === 'embedding' ? '上游默认' : '全部'
                            }
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
              </>
            )}
            <div className='flex flex-wrap items-center gap-3'>
              <Button
                disabled={
                  disabled ||
                  !operation ||
                  unavailable ||
                  unknown ||
                  staleVersion ||
                  (certify && !selectedBinding)
                }
              >
                {busy
                  ? '测试中…'
                  : operation === 'speech'
                    ? '生成语音'
                    : operation === 'image_generation'
                      ? '生成 1 张图片'
                      : '开始测试'}
              </Button>
              <span className='text-sm text-muted-foreground'>
                测试可能产生费用
              </span>
            </div>
          </fieldset>
        </form>
      </Form>
      {sending && (
        <Button
          type='button'
          variant='outline'
          onClick={() => controller.current?.abort()}
        >
          停止等待（上游可能已收费）
        </Button>
      )}
      {!!requestId && (
        <div className='flex min-w-0 flex-col gap-2 text-sm'>
          <p className='break-all text-muted-foreground'>
            本次请求号：{requestId}
          </p>
          {unknown && (
            <p>
              {lookup && lookup.record.status !== 'unconfirmed'
                ? '本次记录已回查；如需再次测试，请明确另起新请求。'
                : '本次结果尚未确认。请按请求号回查；不会自动重新发送。'}
            </p>
          )}
          {staleVersion && (
            <p>渠道配置版本已变化，请刷新渠道后再发起新测试。</p>
          )}
          {(unknown || lookup) && (
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                variant='outline'
                disabled={checking || permissionLost}
                onClick={() => void findRecord()}
              >
                {checking ? '回查中…' : '回查本次记录'}
              </Button>
              {(lookup || lookupMissing) && (
                <Button
                  type='button'
                  variant='outline'
                  disabled={permissionLost || staleVersion}
                  onClick={() => {
                    setUnknown(false)
                    setLookup(null)
                    setLookupMissing(false)
                    setRequestId('')
                    setError(null)
                  }}
                >
                  另起新测试（新请求号）
                </Button>
              )}
            </div>
          )}
        </div>
      )}
      {!!error && <RequestError error={error} />}
      {streamProgress && !permissionLost && (
        <div className='flex min-w-0 flex-col gap-2' aria-live='polite'>
          <p className='text-sm'>
            流式进度：{streamProgress.accepted ? '已受理' : '等待受理'}
          </p>
          {streamProgress.content && (
            <Textarea
              aria-label='流式输出'
              readOnly
              value={streamProgress.content}
              rows={5}
            />
          )}
          {streamProgress.reasoning && (
            <Textarea
              aria-label='思考内容'
              readOnly
              value={streamProgress.reasoning}
              rows={3}
            />
          )}
          {streamProgress.refusal && (
            <p className='text-sm break-words'>
              拒绝说明：{streamProgress.refusal}
            </p>
          )}
          {streamProgress.tools.map((tool, index) => (
            <p key={index} className='text-sm break-words'>
              {tool}
            </p>
          ))}
          {streamProgress.usage && (
            <p className='text-sm'>{streamProgress.usage}</p>
          )}
          {streamProgress.truncated && (
            <p className='text-sm text-muted-foreground'>
              本页增量展示已截断；请以最终状态和请求记录为准。
            </p>
          )}
        </div>
      )}
      {lookup && (
        <div className='flex min-w-0 flex-col gap-2 text-sm' aria-live='polite'>
          <Badge
            variant={
              lookup.record.status === 'success'
                ? 'success'
                : lookup.record.status === 'failure'
                  ? 'destructive'
                  : 'outline'
            }
          >
            {lookup.record.status === 'success'
              ? '成功'
              : lookup.record.status === 'failure'
                ? '失败'
                : '未确认'}
          </Badge>
          <p>
            {lookup.record.model} ·{' '}
            {operationLabels[lookup.record.operation as TestOperation] ??
              lookup.record.operation}
          </p>
          <p className='text-muted-foreground'>
            回查仅恢复元数据和执行证据，正文与媒体不可恢复。
          </p>
          <DiagnosticEvidence
            attempt={lookup.record.attempt}
            healthCertification={lookup.record.health_certification}
          />
        </div>
      )}
      {result && (
        <div className='flex min-w-0 flex-col gap-3' aria-live='polite'>
          <div className='flex flex-wrap items-center gap-2'>
            <Badge
              variant={
                streamTerminalStatus === 'unconfirmed'
                  ? 'outline'
                  : result.ok
                    ? 'success'
                    : 'destructive'
              }
            >
              {streamTerminalStatus === 'unconfirmed'
                ? '未确认'
                : result.ok
                  ? '成功'
                  : '失败'}
            </Badge>
            <span className='text-sm'>{result.duration_ms} ms</span>
          </div>
          <p className='text-sm break-all'>
            {tested} · {result.message}
          </p>
          {result.output && !streamProgress && (
            <Textarea
              aria-label='测试输出'
              readOnly
              value={result.output}
              rows={5}
            />
          )}
          <RetrievalPreview vectors={result.vectors} ranks={result.ranks} />
          {result.audio && (
            <AudioPreview key={result.request_id} audio={result.audio} />
          )}
          {result.image && <GeneratedImagePreview image={result.image} />}
          {result.ok && (
            <p className='text-sm text-muted-foreground'>
              {result.usage_source === 'upstream'
                ? `上游返回用量：${meterLabel(result.operation ?? 'chat', result)}`
                : '上游未返回完整用量'}
            </p>
          )}
          {result.uncertain && (
            <p className='text-sm'>执行结果未确认，可能产生费用</p>
          )}
          <DiagnosticEvidence
            attempt={result.attempt}
            healthCertification={result.health_certification}
          />
        </div>
      )}
      {showHistory && (
        <ChannelTestHistory
          id={channel.id}
          revision={revision}
          busy={busy}
          initialOpen={historyOpen}
        />
      )}
    </div>
  )
}
