import { useEffect, useRef, useState } from 'react'
import { z } from 'zod'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SelectionRow } from '@/components/ui/selection-row'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ChannelPicker } from './channel-model-picker'
import type { Model } from './model-form'
import { ImportPlan, type ImportRows } from './model-import-plan'

type Channel = Schema['ChannelDetail']
type Command = Schema['ImportCommit']
const storedItem = z
  .object({
    upstream_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/),
    action: z.enum(['create', 'link', 'skip']).optional(),
    slug: z.string().max(200).nullable().optional(),
    name: z.string().max(100).nullable().optional(),
    kinds: z
      .array(z.enum(['chat', 'embedding', 'rerank', 'image_generation']))
      .max(4)
      .nullable()
      .optional(),
    target_id: z.string().uuid().nullable().optional(),
  })
  .strict()
const storedCommand = z
  .object({
    channel_id: z.string().uuid(),
    channel_version: z.number().int().positive(),
    request_id: z.string().uuid(),
    revision: z.string().regex(/^[a-f0-9]{64}$/),
    items: z.array(storedItem).min(1).max(50),
  })
  .strict()
  .refine(
    (value) =>
      new Set(value.items.map((item) => item.upstream_id)).size ===
      value.items.length
  )
const storedEnvelope = z
  .object({
    version: z.literal(1),
    tenant_id: z.string(),
    user_id: z.string(),
    command: storedCommand,
  })
  .strict()
type Recovery = { key: string; command: Command | null; malformed: boolean }
function readRecovery(key: string, tenantId: string, userId: string): Recovery {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return { key, command: null, malformed: false }
    const value: unknown = JSON.parse(raw)
    const envelope = storedEnvelope.safeParse(value)
    if (
      envelope.success &&
      envelope.data.tenant_id === tenantId &&
      envelope.data.user_id === userId
    )
      return {
        key,
        command: envelope.data.command as Command,
        malformed: false,
      }
    // Older releases stored the command directly under this same scoped key.
    const legacy = storedCommand.safeParse(value)
    if (legacy.success)
      return { key, command: legacy.data as Command, malformed: false }
  } catch {
    // Preserve an unreadable record; it may represent a completed submission.
  }
  return { key, command: null, malformed: true }
}
const resultLabels = {
  created: '已创建',
  linked: '已关联',
  unchanged: '已存在',
  skipped: '已跳过',
}

type ImportProps = {
  close: () => void
  configure: (model: Model) => void
  restoreFocus?: () => void
  initialSource?: Channel
  initialIds?: string[]
}

export function ModelImport(props: ImportProps) {
  const { organization, user } = useOrganization()
  return (
    <ScopedModelImport
      key={`${organization.tenant_id}:${user.id}`}
      {...props}
    />
  )
}

function ScopedModelImport({
  close,
  configure,
  restoreFocus,
  initialSource,
  initialIds,
}: ImportProps) {
  const { organization, csrf, user } = useOrganization()
  const client = useQueryClient()
  const storageKey = 'model-import:' + organization.tenant_id + ':' + user.id
  const [recovery, setRecovery] = useState<Recovery>(() =>
    readRecovery(storageKey, organization.tenant_id, user.id)
  )
  const pending = recovery.command
  const malformed = recovery.malformed
  const [source, setSource] = useState<Channel | null>(null)
  const [selected, setSelected] = useState<string[]>(
    initialIds?.length && initialIds.length <= 50 && !pending && !malformed
      ? initialIds
      : []
  )
  const [selectionLocked, setSelectionLocked] = useState(false)
  const [preview, setPreview] = useState<Schema['ImportPreview'] | null>(null)
  const [request, setRequest] = useState<Schema['ImportInput'] | null>(null)
  const [result, setResult] = useState<Schema['ImportResult'] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(
    initialSource && initialIds && initialIds.length > 50
      ? new Error('一次最多导入 50 个上游模型，请重新选择。')
      : null
  )
  const [confirmClose, setConfirmClose] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [permissionLost, setPermissionLost] = useState(false)
  const [unpreviewed, setUnpreviewed] = useState<{
    channel: Channel
    rows: Schema['ImportItem'][]
  } | null>(null)
  const [rejectedCommand, setRejectedCommand] = useState<Command | null>(null)
  const [initializing, setInitializing] = useState(
    Boolean(
      initialSource &&
      initialIds?.length &&
      initialIds.length <= 50 &&
      !pending &&
      !malformed
    )
  )
  const initialized = useRef(false)

  function remember(command: Command | null) {
    if (command)
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({
          version: 1,
          tenant_id: organization.tenant_id,
          user_id: user.id,
          command,
        })
      )
    else sessionStorage.removeItem(storageKey)
    setRecovery({ key: storageKey, command, malformed: false })
  }
  function completed(value: Schema['ImportResult']) {
    setResult(value)
    remember(null)
    setError(null)
    void client.invalidateQueries({
      queryKey: ['organization', organization.tenant_id, 'model-catalog'],
    })
  }
  async function inspect(command: Command) {
    const status = await api<Schema['ImportStatus']>(
      '/llm/model-imports/' + command.request_id
    )
    if (status.committed && status.result) {
      if (status.result.request_id !== command.request_id)
        throw new Error('回执标识不匹配，请保留本地记录并联系管理员。')
      completed(status.result)
      return true
    }
    if (status.committed || status.result)
      throw new Error('回执状态不完整，请保留本地记录并稍后重试。')
    return false
  }
  async function submit(command: Command) {
    if (permissionLost || malformed || busy) return
    setBusy(true)
    setError(null)
    try {
      // Persist the exact command before sending so a reload cannot create a second batch.
      if (pending?.request_id !== command.request_id) remember(command)
      if (await inspect(command)) return
      try {
        const value = await api<Schema['ImportResult']>(
          '/llm/model-imports/commit',
          'POST',
          command,
          csrf
        )
        if (value.request_id !== command.request_id)
          throw new Error('导入结果标识不匹配，请保留本地记录并查询回执。')
        completed(value)
      } catch (commitError) {
        if (
          commitError instanceof ApiError &&
          [409, 422].includes(commitError.status)
        ) {
          // The server rejected this write. Keep the reviewed rows for re-preview.
          remember(null)
          setRequest(null)
          setRejectedCommand(command)
          setSelected(command.items.map((item) => item.upstream_id))
          setError(commitError)
          return
        }
        if (commitError instanceof ApiError && commitError.status === 403) {
          setPermissionLost(true)
          setError(commitError)
          return
        }
        try {
          if (await inspect(command)) return
          setError(commitError)
        } catch (receiptError) {
          if (receiptError instanceof ApiError && receiptError.status === 403)
            setPermissionLost(true)
          setError(receiptError)
        }
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setPermissionLost(true)
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  async function checkReceipt() {
    if (!pending) return
    setBusy(true)
    setError(null)
    try {
      if (!(await inspect(pending)))
        setError(new Error('尚未确认导入结果，可安全重试原提交。'))
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setPermissionLost(true)
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  async function loadPreview(
    channel: Channel,
    rows: Schema['ImportItem'][],
    refresh = false
  ) {
    if (permissionLost || malformed) return
    setBusy(true)
    setError(null)
    setRequest(null)
    setSource(channel)
    setUnpreviewed({ channel, rows })
    try {
      const current = refresh
        ? await api<Channel>('/llm/channels/' + channel.id)
        : channel
      const body = {
        channel_id: current.id,
        channel_version: current.version,
        items: rows,
      }
      const next = await api<Schema['ImportPreview']>(
        '/llm/model-imports/preview',
        'POST',
        body,
        csrf
      )
      setSource(current)
      setPreview(next)
      setRequest(body)
      setUnpreviewed(null)
      setRejectedCommand(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setPermissionLost(true)
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  async function repreviewRejected() {
    if (!rejectedCommand || permissionLost || busy) return
    setBusy(true)
    setError(null)
    try {
      const current = await api<Channel>(
        '/llm/channels/' + rejectedCommand.channel_id
      )
      const rows = rejectedCommand.items
      setRejectedCommand(null)
      await loadPreview(current, rows)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403)
        setPermissionLost(true)
      setError(cause)
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => {
    if (
      initialized.current ||
      !initialSource ||
      !initialIds?.length ||
      pending ||
      malformed
    )
      return
    initialized.current = true
    if (initialIds.length > 50) return
    void Promise.resolve()
      .then(() =>
        loadPreview(
          initialSource,
          initialIds.map((id) => ({ upstream_id: id, action: 'create' }))
        )
      )
      .finally(() => setInitializing(false))
    // The initial source is a one-time entry context. Later selection stays local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  function closeRequested() {
    if (busy) return
    if (
      !result &&
      (selected.length ||
        selectionLocked ||
        pending ||
        malformed ||
        unpreviewed ||
        rejectedCommand)
    )
      setConfirmClose(true)
    else close()
  }
  function reset() {
    setSource(null)
    setSelected([])
    setPreview(null)
    setRequest(null)
    setSelectionLocked(false)
    setUnpreviewed(null)
    setRejectedCommand(null)
    setError(null)
    setConfirmReset(false)
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) closeRequested()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-4xl'
        aria-describedby={undefined}
        onCloseAutoFocus={
          restoreFocus
            ? (event) => {
                event.preventDefault()
                restoreFocus()
              }
            : undefined
        }
      >
        <SheetHeader className='px-4 pr-12 sm:px-6'>
          <SheetTitle>
            {result
              ? '导入结果'
              : pending || malformed
                ? '确认导入结果'
                : '从渠道批量导入'}
          </SheetTitle>
        </SheetHeader>
        <Separator />
        <div className='flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4 sm:p-6'>
          {!!error && <RequestError error={error} />}
          {result ? (
            <div className='flex flex-col gap-3'>
              <p className='text-sm break-all text-muted-foreground'>
                本次整批已提交 · 请求号 {result.request_id}
              </p>
              {result.items.map((item) => (
                <div
                  key={item.upstream_id}
                  className='flex flex-wrap items-center justify-between gap-2 rounded-lg border p-4'
                >
                  <div className='min-w-0 space-y-2'>
                    <p className='break-all'>{item.slug ?? item.upstream_id}</p>
                    <Badge variant='secondary'>
                      {resultLabels[item.status]}
                    </Badge>
                  </div>
                  {item.model_id && (
                    <Button
                      variant='outline'
                      disabled={busy || permissionLost}
                      onClick={async () => {
                        setBusy(true)
                        setError(null)
                        try {
                          configure(
                            await api<Model>('/llm/models/' + item.model_id)
                          )
                        } catch (e) {
                          if (e instanceof ApiError && e.status === 403)
                            setPermissionLost(true)
                          setError(e)
                        } finally {
                          setBusy(false)
                        }
                      }}
                    >
                      配置模型
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : malformed ? (
            <div className='space-y-4'>
              <p>
                本地待确认导入记录无法安全读取，未发送新提交。可能已有导入完成，请保留记录核对。
              </p>
              <Button
                variant='outline'
                disabled={busy}
                onClick={() => setConfirmDiscard(true)}
              >
                丢弃本地记录
              </Button>
            </div>
          ) : pending ? (
            <div className='space-y-4'>
              <p>提交结果待确认，请查询结果或重试原提交。</p>
              <p className='text-sm break-all text-muted-foreground'>
                请求号 {pending.request_id}
              </p>
              <div className='flex flex-wrap gap-2'>
                <Button
                  variant='outline'
                  disabled={busy || permissionLost}
                  onClick={() => void checkReceipt()}
                >
                  查询结果
                </Button>
                <Button
                  disabled={busy || permissionLost}
                  onClick={() => void submit(pending)}
                >
                  重试原提交
                </Button>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() => setConfirmDiscard(true)}
                >
                  丢弃本地记录
                </Button>
              </div>
            </div>
          ) : initializing ? (
            <LoadingState />
          ) : source && preview ? (
            <>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <span>
                  {source.name} · {selected.length} 个上游模型
                </span>
                <Button
                  variant='outline'
                  disabled={busy || permissionLost}
                  onClick={() => setConfirmReset(true)}
                >
                  重新选择
                </Button>
              </div>
              <ImportPlan
                key={selected.join('|')}
                preview={preview}
                disabled={busy || permissionLost}
                onEdit={() => {
                  setRequest(null)
                  setError(null)
                }}
                onPreview={(rows: ImportRows) =>
                  void loadPreview(source, rows, true)
                }
                onPermissionLost={setPermissionLost}
              />
              {request && (
                <p role='status' className='text-sm text-muted-foreground'>
                  新建 {preview.create_count} 个 · 关联 {preview.link_count} 个
                  · 新增 {preview.binding_count} 条渠道绑定
                </p>
              )}
            </>
          ) : unpreviewed ? (
            <div className='flex flex-col gap-4'>
              <p>
                {unpreviewed.channel.name} · {unpreviewed.rows.length}{' '}
                个上游模型
              </p>
              <p className='text-sm text-muted-foreground'>
                预览未完成，原选择仍保留。
              </p>
              <div className='flex flex-wrap gap-2'>
                <Button
                  disabled={busy || permissionLost}
                  onClick={() =>
                    void loadPreview(
                      unpreviewed.channel,
                      unpreviewed.rows,
                      true
                    )
                  }
                >
                  重试预览
                </Button>
                <Button
                  variant='outline'
                  disabled={busy || permissionLost}
                  onClick={() => setConfirmReset(true)}
                >
                  重新选择
                </Button>
              </div>
            </div>
          ) : rejectedCommand ? (
            <div className='flex flex-col gap-4'>
              <p>
                本次提交未写入。{rejectedCommand.items.length}{' '}
                行选择与修改已保留，请重新预览。
              </p>
              <p className='text-sm break-all text-muted-foreground'>
                来源渠道 {rejectedCommand.channel_id}
              </p>
              <Button
                className='self-start'
                disabled={busy || permissionLost}
                onClick={() => void repreviewRejected()}
              >
                重新预览保留的行
              </Button>
            </div>
          ) : (
            <>
              <ChannelPicker
                disabled={selectionLocked || busy || permissionLost}
              >
                {(channel) => (
                  <ImportSelection
                    key={channel.id}
                    channel={channel}
                    disabled={busy || permissionLost}
                    onSelection={(ids) => {
                      setSource(channel)
                      setSelected(ids)
                      setSelectionLocked(!!ids.length)
                    }}
                  />
                )}
              </ChannelPicker>
            </>
          )}
        </div>
        <Separator />
        <SheetFooter className='flex-row flex-wrap items-center justify-end px-4 sm:px-6'>
          {preview && !pending && !result && (
            <span className='mr-auto text-sm text-muted-foreground'>
              新增模型和关联保持关闭
            </span>
          )}
          <Button variant='outline' disabled={busy} onClick={closeRequested}>
            {result ? '完成' : '关闭'}
          </Button>
          {!preview &&
            !pending &&
            !result &&
            !unpreviewed &&
            !malformed &&
            source &&
            selected.length > 0 && (
              <Button
                disabled={busy || permissionLost || initializing}
                onClick={() =>
                  void loadPreview(
                    source,
                    selected.map((id) => ({
                      upstream_id: id,
                      action: 'create',
                    }))
                  )
                }
              >
                预览导入（{selected.length}）
              </Button>
            )}
          {preview && !pending && !result && (
            <Button
              disabled={
                busy || permissionLost || !request || !preview.can_commit
              }
              onClick={() => {
                if (request)
                  void submit({
                    ...request,
                    revision: preview.revision,
                    request_id: crypto.randomUUID(),
                  })
              }}
            >
              {busy ? '处理中…' : '确认导入'}
            </Button>
          )}
        </SheetFooter>
        <ConfirmDialog
          open={confirmClose}
          onOpenChange={setConfirmClose}
          title={pending || malformed ? '关闭导入窗口？' : '放弃本次选择？'}
          desc={
            pending || malformed
              ? '再次打开批量导入可继续查询本次结果。'
              : '尚未提交的选择和修改将被清除。'
          }
          cancelBtnText='继续编辑'
          confirmText='关闭'
          handleConfirm={close}
        />
        <ConfirmDialog
          open={confirmReset}
          onOpenChange={setConfirmReset}
          title='重新选择模型？'
          desc='本次预览中的修改将被清除。'
          cancelBtnText='取消'
          confirmText='重新选择'
          handleConfirm={reset}
        />
        <ConfirmDialog
          open={confirmDiscard}
          onOpenChange={setConfirmDiscard}
          title='丢弃本地导入记录？'
          desc='导入可能已经完成。此操作只删除本浏览器的恢复记录，不会撤回服务器上的导入。请先核对模型。'
          cancelBtnText='保留记录'
          confirmText='仍要丢弃'
          handleConfirm={() => {
            remember(null)
            reset()
            setConfirmDiscard(false)
          }}
        />
      </SheetContent>
    </Sheet>
  )
}

function ImportSelection({
  channel,
  disabled,
  onSelection,
}: {
  channel: Channel
  disabled: boolean
  onSelection: (ids: string[]) => void
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const matches = channel.models.filter((model) =>
    model.id.toLowerCase().includes(search.toLowerCase())
  )
  const visible = matches.slice((page - 1) * 20, page * 20)
  const all =
    visible.length > 0 && visible.every((model) => selected.includes(model.id))
  function change(ids: string[]) {
    setSelected(ids)
    onSelection(ids)
  }
  return (
    <div className='flex flex-col gap-4'>
      <div className='space-y-2'>
        <Label htmlFor='batch-model-search'>搜索上游模型</Label>
        <Input
          id='batch-model-search'
          value={search}
          disabled={disabled}
          placeholder='模型 ID'
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
      </div>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <SelectionRow>
          <Checkbox
            checked={all}
            disabled={
              disabled ||
              !visible.length ||
              (!all &&
                new Set([...selected, ...visible.map((m) => m.id)]).size > 50)
            }
            onCheckedChange={(checked) =>
              change(
                checked
                  ? [...new Set([...selected, ...visible.map((m) => m.id)])]
                  : selected.filter((id) => !visible.some((m) => m.id === id))
              )
            }
          />
          本页全选
        </SelectionRow>
        <span className='text-sm'>已选 {selected.length} / 50</span>
        <Button
          variant='ghost'
          disabled={disabled || !selected.length}
          onClick={() => change([])}
        >
          清除选择
        </Button>
      </div>
      <div className='rounded-lg border p-2'>
        {visible.map((model) => (
          <SelectionRow key={model.id} className='min-w-0'>
            <Checkbox
              aria-label={'选择 ' + model.id}
              disabled={
                disabled ||
                (selected.length >= 50 && !selected.includes(model.id))
              }
              checked={selected.includes(model.id)}
              onCheckedChange={(checked) =>
                change(
                  checked
                    ? [...selected, model.id]
                    : selected.filter((id) => id !== model.id)
                )
              }
            />
            <span className='min-w-0 break-all'>{model.id}</span>
          </SelectionRow>
        ))}
        {!visible.length && (
          <p className='p-4 text-sm text-muted-foreground'>
            {channel.models.length ? '没有匹配的模型' : '此渠道还没有登记模型'}
          </p>
        )}
      </div>
      {matches.length > 20 && (
        <div className='flex items-center justify-between gap-2'>
          <Button
            variant='outline'
            size='sm'
            disabled={disabled || page === 1}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </Button>
          <span className='text-sm'>
            第 {page} / {Math.ceil(matches.length / 20)} 页
          </span>
          <Button
            variant='outline'
            size='sm'
            disabled={disabled || page * 20 >= matches.length}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  )
}
