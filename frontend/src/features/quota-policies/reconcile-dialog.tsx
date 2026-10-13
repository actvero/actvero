import { useEffect, useRef, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  emptyReconcileValues,
  fieldNames,
  metricFields,
  reconcileBody,
  reconcileSchema,
  type Metric,
  type ReconcileValues,
} from './reconcile-form'
import {
  readRecovery,
  recoveryKey,
  type ReconcileRecovery,
} from './reconcile-recovery'

type Context = Schema['ReconciliationContext']
type Preview = Schema['ReconciliationPreview']
type Command = ReturnType<typeof reconcileBody> & { request_id: string }
type Recovery = ReconcileRecovery
const labels = {
  reserved: '预占中',
  review: '待核对',
  settled: '已结算',
  released: '已释放',
} as const

function uncertainFailure(error: unknown) {
  return !(error instanceof ApiError) || error.status >= 500
}

export function ReconcileDialog({
  callId,
  close,
  saved,
  restoreFocus,
  onForbidden,
}: {
  callId: string
  close: () => void
  saved: () => void
  restoreFocus: () => void
  onForbidden?: (cause: ApiError) => void
}) {
  const { organization, user, csrf } = useOrganization()
  const storageKey = recoveryKey(organization.tenant_id, user.id, callId)
  const [recovery, setRecovery] = useState<Recovery | null>(() =>
    readRecovery(storageKey, callId)
  )
  const [command, setCommand] = useState<Command | null>(null)
  const [unknown, setUnknown] = useState(Boolean(recovery))
  const [receiptMissing, setReceiptMissing] = useState(false)
  const [context, setContext] = useState<Context | null>(null)
  const contextRef = useRef<Context | null>(null)
  contextRef.current = context
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewSignature, setPreviewSignature] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [forbidden, setForbidden] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)
  const [confirmRestart, setConfirmRestart] = useState(false)
  const working = useRef(false)
  const alive = useRef(true)
  const accessRevoked = useRef(false)
  const loadingController = useRef<AbortController | null>(null)
  const form = useForm<ReconcileValues>({
    resolver: (values, resolverContext, options) =>
      zodResolver(
        reconcileSchema(
          contextRef.current?.required_fields ?? [],
          contextRef.current?.price.metric ?? 'tokens'
        )
      )(values, resolverContext, options),
    defaultValues: emptyReconcileValues,
  })
  const watched = useWatch({ control: form.control })
  const action = watched.action ?? 'settle'
  const currentSignature = context
    ? JSON.stringify(
        reconcileBody(
          form.getValues(),
          context.price.metric as Metric,
          context.settlement.version
        )
      )
    : null
  const previewValid = Boolean(preview && previewSignature === currentSignature)
  const path = `/llm/settlements/${callId}`

  function forget() {
    try {
      sessionStorage.removeItem(storageKey)
    } catch {
      // The in-memory state still prevents a second submission in this view.
    }
    setRecovery(null)
    setCommand(null)
    setUnknown(false)
    setReceiptMissing(false)
  }

  function remember(next: Command) {
    const ids = { call_id: callId, request_id: next.request_id }
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(ids))
    } catch {
      setError(
        new Error(
          '浏览器无法保存回查编号，本次核对尚未发送。请检查浏览器存储后重试。'
        )
      )
      return false
    }
    setRecovery(ids)
    setCommand(next)
    return true
  }

  function deny(cause: unknown) {
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      accessRevoked.current = true
      loadingController.current?.abort()
      forget()
      setContext(null)
      setPreview(null)
      setPreviewSignature(null)
      setForbidden(true)
      setError(cause)
      onForbidden?.(cause)
      return true
    }
    return false
  }

  async function loadLatest() {
    if (accessRevoked.current) return
    loadingController.current?.abort()
    const controller = new AbortController()
    loadingController.current = controller
    setLoading(true)
    setError(null)
    try {
      const latest = await api<Context>(
        path + '/reconciliation',
        'GET',
        undefined,
        undefined,
        controller.signal
      )
      if (controller.signal.aborted || !alive.current || accessRevoked.current)
        return
      if (latest.settlement.id !== callId)
        throw new Error('核对记录与所选调用不符，请刷新列表。')
      setContext(latest)
      setConflict(false)
      setPreview(null)
      setPreviewSignature(null)
    } catch (cause) {
      if (controller.signal.aborted || !alive.current || accessRevoked.current)
        return
      if (!deny(cause)) setError(cause)
    } finally {
      if (!controller.signal.aborted && alive.current) setLoading(false)
    }
  }

  useEffect(() => {
    alive.current = true
    let active = true
    queueMicrotask(() => {
      if (!active) return
      void loadLatest()
      if (recovery) void checkReceipt()
    })
    return () => {
      active = false
      alive.current = false
      loadingController.current?.abort()
    }
    // callId is fixed for the lifetime of this dialog; changing it remounts the caller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callId])

  function requestClose() {
    if (working.current) return
    if (form.formState.isDirty || unknown) setConfirmClose(true)
    else close()
  }

  async function withWork(run: () => Promise<void>) {
    if (working.current || forbidden || accessRevoked.current) return
    working.current = true
    setBusy(true)
    setError(null)
    try {
      await run()
    } finally {
      working.current = false
      if (alive.current) setBusy(false)
    }
  }

  async function previewSubmission(values: ReconcileValues) {
    if (!context || conflict || unknown || !context.eligible) return
    await withWork(async () => {
      const body = reconcileBody(
        values,
        context.price.metric as Metric,
        context.settlement.version
      )
      try {
        const result = await api<Preview>(
          path + '/reconcile/preview',
          'POST',
          body,
          csrf
        )
        if (!alive.current || accessRevoked.current) return
        if (
          result.call_id !== callId ||
          result.version !== body.version ||
          result.action !== body.action ||
          result.metric !== context.price.metric ||
          result.currency !== context.currency
        )
          throw new Error('预览与当前记录不一致，请重新读取服务端记录。')
        setPreview(result)
        setPreviewSignature(JSON.stringify(body))
      } catch (cause) {
        if (!alive.current || accessRevoked.current) return
        if (!deny(cause)) {
          if (cause instanceof ApiError && cause.status === 409)
            setConflict(true)
          setPreview(null)
          setPreviewSignature(null)
          setError(cause)
        }
      }
    })
  }

  async function queryReceipt(
    ids: Recovery
  ): Promise<'completed' | 'missing' | 'pending' | 'forbidden'> {
    try {
      const receipt = await api<Schema['MutationReceiptView']>(
        `/llm/mutation-receipts/${ids.request_id}?scope=settlement.reconcile`
      )
      if (!alive.current || accessRevoked.current) return 'forbidden'
      if (
        receipt.request_id !== ids.request_id ||
        receipt.resource_id !== callId ||
        receipt.scope !== 'settlement.reconcile' ||
        receipt.state !== 'completed'
      )
        throw new Error('回执与本次核对不符，请保留请求号联系管理员。')
      forget()
      saved()
      return 'completed'
    } catch (cause) {
      if (!alive.current || accessRevoked.current) return 'forbidden'
      if (cause instanceof ApiError && cause.status === 404) {
        setReceiptMissing(true)
        return 'missing'
      }
      if (deny(cause)) return 'forbidden'
      setError(cause)
      return 'pending'
    }
  }

  async function checkReceipt() {
    if (!recovery) return
    await withWork(async () => {
      const status = await queryReceipt(recovery)
      if (status === 'missing' && alive.current)
        setError(new Error('尚无完成回执；请求可能仍在处理，请稍后回查。'))
    })
  }

  async function send(original: Command) {
    try {
      await api<Schema['SettlementPage']>(
        path + '/reconcile',
        'POST',
        original,
        csrf
      )
      if (!alive.current) return
      forget()
      saved()
    } catch (cause) {
      if (!alive.current) return
      if (deny(cause)) return
      if (cause instanceof ApiError && [409, 422].includes(cause.status)) {
        forget()
        setPreview(null)
        setPreviewSignature(null)
        if (cause.status === 409) setConflict(true)
        setError(cause)
        return
      }
      if (uncertainFailure(cause)) {
        setUnknown(true)
        const state = await queryReceipt({
          call_id: callId,
          request_id: original.request_id,
        })
        if (alive.current && state !== 'completed' && state !== 'forbidden')
          setError(cause)
        return
      }
      forget()
      setError(cause)
    }
  }

  async function confirmSubmission(values: ReconcileValues) {
    if (!context || conflict || unknown || !context.eligible || !previewValid)
      return
    const body = reconcileBody(
      values,
      context.price.metric as Metric,
      context.settlement.version
    )
    if (JSON.stringify(body) !== previewSignature) return
    await withWork(async () => {
      const next = { ...body, request_id: crypto.randomUUID() }
      if (!remember(next)) return
      await send(next)
    })
  }

  async function retryOriginal() {
    if (!command || !recovery || !unknown || !receiptMissing) return
    await withWork(async () => {
      if ((await queryReceipt(recovery)) === 'missing' && alive.current)
        await send(command)
    })
  }

  const settlement = context?.settlement
  const metric = context?.price.metric as Metric | undefined
  const fields = metric ? metricFields[metric] : []
  const blocked =
    busy || loading || forbidden || conflict || unknown || !context?.eligible
  const rates = context
    ? (
        [
          [metric === 'tokens' ? '输入' : '单价', context.price.input],
          ['输出', context.price.output],
          ['缓存读取', context.price.cache_read],
          ['缓存写入 5 分钟', context.price.cache_write_5m],
          ['缓存写入 1 小时', context.price.cache_write_1h],
        ] as const
      ).filter(([, value]) => value !== null)
    : []

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && requestClose()}>
        <DialogContent
          className='flex max-h-[90dvh] min-w-0 flex-col overflow-hidden sm:max-w-2xl'
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            restoreFocus()
          }}
        >
          <DialogHeader className='shrink-0 text-start'>
            <DialogTitle>
              核对用量 · {settlement?.model_name ?? callId}
            </DialogTitle>
            {settlement && (
              <div className='flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
                <span>{settlement.member_name}</span>
                <Badge variant='outline'>
                  {labels[settlement.status as keyof typeof labels]}
                </Badge>
                <span>预占 {settlement.reserved_points} 积分</span>
              </div>
            )}
          </DialogHeader>
          {forbidden ? (
            <div className='min-h-0 overflow-y-auto'>
              <RequestError error={error} />
              <p className='mt-3 text-sm text-muted-foreground'>
                记录不可访问或权限已变化；请刷新列表或重新登录。
              </p>
            </div>
          ) : !context && loading ? (
            <LoadingState />
          ) : !context ? (
            <div className='min-h-0 overflow-y-auto'>
              <RequestError error={error} retry={() => void loadLatest()} />
            </div>
          ) : (
            <Form {...form}>
              <form
                className='flex min-h-0 flex-1 flex-col gap-4'
                onSubmit={(event) =>
                  void form.handleSubmit(previewSubmission)(event)
                }
              >
                <div className='min-h-0 flex-1 overflow-y-auto pr-1'>
                  <fieldset
                    disabled={blocked}
                    className='flex min-w-0 flex-col gap-4'
                  >
                    <p className='text-sm text-muted-foreground'>
                      按本次受理时保存的预算价格与积分比例核对全部尝试；缺失用量不能当作零。
                    </p>
                    <p className='text-sm text-muted-foreground'>
                      计量单位：
                      {metric === 'tokens'
                        ? 'Token'
                        : metric === 'characters'
                          ? '字符'
                          : metric === 'search_units'
                            ? '搜索单位'
                            : '张'}
                      · 积分比例 {context.ratio} 积分 / {context.currency}
                    </p>
                    <div className='flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground'>
                      {rates.map(([label, value]) => (
                        <span key={label}>
                          {label} {value} {context.currency} /{' '}
                          {context.price.unit}
                        </span>
                      ))}
                    </div>
                    {!context.eligible && (
                      <Alert>
                        <AlertTitle>当前不能核对</AlertTitle>
                        <AlertDescription>
                          {context.available_after
                            ? `请求仍可能在执行；${dateTime(context.available_after)} 后再刷新。`
                            : '记录已经处理或状态已变化，请刷新。'}
                        </AlertDescription>
                      </Alert>
                    )}
                    {conflict && (
                      <Alert>
                        <AlertTitle>服务端记录已变化</AlertTitle>
                        <AlertDescription>
                          保留了当前输入。请先刷新服务端记录，再重新预览和确认。
                        </AlertDescription>
                      </Alert>
                    )}
                    {unknown && recovery && (
                      <Alert>
                        <AlertTitle>结果尚未确认</AlertTitle>
                        <AlertDescription>
                          请求号{' '}
                          <span className='font-mono break-all'>
                            {recovery.request_id}
                          </span>
                          。先查询原回执；不会生成新编号自动重发。
                        </AlertDescription>
                      </Alert>
                    )}
                    {preview && !previewValid && !unknown && (
                      <p className='text-sm text-muted-foreground'>
                        输入已修改，原预览失效，请重新预览。
                      </p>
                    )}
                    {!unknown && (
                      <>
                        <FormField
                          control={form.control}
                          name='action'
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>处理方式</FormLabel>
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
                                    <SelectItem value='settle'>
                                      按真实用量结算
                                    </SelectItem>
                                    <SelectItem value='release'>
                                      确认无使用，释放预占
                                    </SelectItem>
                                  </SelectGroup>
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                        {action === 'settle' ? (
                          <div className='grid gap-3 sm:grid-cols-2'>
                            {fields.map((name) => (
                              <FormField
                                key={name}
                                control={form.control}
                                name={name}
                                render={({ field }) => (
                                  <FormItem>
                                    <FormLabel>
                                      {fieldNames[name]}
                                      {context.required_fields.includes(name)
                                        ? ' *'
                                        : '（选填）'}
                                    </FormLabel>
                                    <FormControl>
                                      <Input
                                        {...field}
                                        inputMode='numeric'
                                        placeholder='确认是零时填写 0'
                                      />
                                    </FormControl>
                                    <FormMessage />
                                  </FormItem>
                                )}
                              />
                            ))}
                          </div>
                        ) : (
                          <FormField
                            control={form.control}
                            name='release_confirmed'
                            render={({ field }) => (
                              <FormItem>
                                <div className='flex items-start gap-3'>
                                  <FormControl>
                                    <Checkbox
                                      checked={field.value}
                                      onCheckedChange={field.onChange}
                                    />
                                  </FormControl>
                                  <FormLabel className='font-normal'>
                                    已依据外部记录确认没有使用量
                                  </FormLabel>
                                </div>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        )}
                        <FormField
                          control={form.control}
                          name='reason'
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>核对依据</FormLabel>
                              <FormControl>
                                <Textarea
                                  {...field}
                                  placeholder='填写上游账单或确认无消耗的依据'
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </>
                    )}
                    {previewValid && preview && !unknown && (
                      <Alert>
                        <AlertTitle>按历史快照预览</AlertTitle>
                        <AlertDescription>
                          <span>
                            {preview.action === 'release'
                              ? `本次消耗 0 积分，释放预占 ${settlement?.reserved_points ?? '—'} 积分`
                              : `结算金额：${preview.amount} ${preview.currency}；消耗 ${preview.points} 积分`}
                          </span>
                          {preview.action === 'settle' && (
                            <span>
                              {Object.entries(preview.usage)
                                .filter(([name]) => name in fieldNames)
                                .map(
                                  ([name, value]) =>
                                    `${fieldNames[name as keyof typeof fieldNames]} ${value}`
                                )
                                .join(' · ')}
                            </span>
                          )}
                        </AlertDescription>
                      </Alert>
                    )}
                    {error !== null && <RequestError error={error} />}
                  </fieldset>
                </div>
                <DialogFooter className='shrink-0 border-t bg-background pt-3'>
                  <Button
                    type='button'
                    variant='outline'
                    disabled={busy}
                    onClick={requestClose}
                  >
                    取消
                  </Button>
                  {unknown && recovery ? (
                    <>
                      <Button
                        type='button'
                        disabled={busy}
                        onClick={() => void checkReceipt()}
                      >
                        查询原回执
                      </Button>
                      {receiptMissing && command && (
                        <Button
                          type='button'
                          variant='outline'
                          disabled={busy}
                          onClick={() => void retryOriginal()}
                        >
                          同编号重试原提交
                        </Button>
                      )}
                      {receiptMissing && !command && (
                        <Button
                          type='button'
                          variant='outline'
                          disabled={busy}
                          onClick={() => setConfirmRestart(true)}
                        >
                          重新开始核对
                        </Button>
                      )}
                    </>
                  ) : conflict || !context.eligible ? (
                    <Button
                      type='button'
                      disabled={busy}
                      onClick={() => void loadLatest()}
                    >
                      刷新服务端记录
                    </Button>
                  ) : (
                    <>
                      <Button type='submit' variant='outline' disabled={busy}>
                        {busy ? '处理中…' : '查看结算预览'}
                      </Button>
                      <Button
                        type='button'
                        disabled={busy || !previewValid}
                        onClick={() =>
                          void form.handleSubmit(confirmSubmission)()
                        }
                      >
                        {action === 'release' ? '确认释放' : '确认结算'}
                      </Button>
                    </>
                  )}
                </DialogFooter>
              </form>
            </Form>
          )}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title='离开核对？'
        desc={
          unknown
            ? '本次请求号会保留供回查；核对内容不会保存在浏览器中。'
            : '未提交的核对输入将丢弃。'
        }
        confirmText='离开'
        cancelBtnText='继续核对'
        handleConfirm={() => {
          setConfirmClose(false)
          close()
        }}
      />
      <ConfirmDialog
        open={confirmRestart}
        onOpenChange={setConfirmRestart}
        title='重新开始核对？'
        desc='原请求可能仍在处理。会先读取最新记录；新提交仍须重新预览并经服务端版本检查。'
        confirmText='读取最新记录'
        cancelBtnText='继续回查'
        handleConfirm={() => {
          setConfirmRestart(false)
          forget()
          setPreview(null)
          setPreviewSignature(null)
          void loadLatest()
        }}
      />
    </>
  )
}
