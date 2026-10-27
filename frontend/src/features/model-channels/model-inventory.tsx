import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Download, Plus, Search, Trash2 } from 'lucide-react'
import { api, ApiError, dateTime } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Form,
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
import { SelectionRow } from '@/components/ui/selection-row'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ModelCreate } from '@/features/model-catalog/model-create'
import { ModelEditor } from '@/features/model-catalog/model-editor'
import type { Model } from '@/features/model-catalog/model-form'
import { ModelImport } from '@/features/model-catalog/model-import'
import { channelPath } from './api'
import { type Detail, type Discovery } from './shared'

const ids = (value: string) => [
  ...new Set(
    value
      .split(/[\n,]/)
      .map((v) => v.trim())
      .filter(Boolean)
  ),
]
const schema = z.object({
  models: z
    .string()
    .refine((value) => ids(value).length > 0, '至少填写一个模型 ID')
    .refine(
      (value) =>
        ids(value).length <= 1000 &&
        ids(value).every((id) =>
          /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/.test(id)
        ),
      '每行一个模型 ID，最多 1000 个；支持字母、数字和 . _ : / @ + -'
    ),
})

export function ModelInventory({
  channel,
  modelDiscovery,
  changed,
  busy,
  setBusy,
}: {
  channel: Detail
  modelDiscovery: boolean
  changed: (channel: Detail) => void
  busy: boolean
  setBusy: (busy: boolean) => void
}) {
  const { csrf } = useOrganization()
  const [error, setError] = useState<unknown>(null)
  const preview = channel.model_directory
  const [selected, setSelected] = useState<string[]>([])
  const [previewSearch, setPreviewSearch] = useState('')
  const [search, setSearch] = useState('')
  const [source, setSource] = useState('all')
  const [notice, setNotice] = useState('')
  const [registeredSelection, setRegisteredSelection] = useState<string[]>([])
  const [removeId, setRemoveId] = useState<string | null>(null)
  const [importIds, setImportIds] = useState<string[] | null>(null)
  const [modelEditor, setModelEditor] = useState<Model | null>(null)
  const [createSource, setCreateSource] = useState<{
    channel: Detail
    upstream: string
  } | null>(null)
  const [permissionLost, setPermissionLost] = useState(false)
  const importTrigger = useRef<HTMLElement | null>(null)
  const editorTrigger = useRef<HTMLElement | null>(null)
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { models: '' },
  })
  const registered = new Set(channel.models.map((model) => model.id))
  const candidates =
    preview?.candidates?.filter((model) => !registered.has(model.id)) ?? []
  const matches = candidates.filter((model) =>
    model.id.toLowerCase().includes(previewSearch.trim().toLowerCase())
  )
  const allMatchedSelected =
    matches.length > 0 && matches.every((model) => selected.includes(model.id))
  const disabled = busy || channel.archived || permissionLost
  const bindingReferences = channel.binding_references ?? []
  const visible = channel.models.filter(
    (model) =>
      model.id.toLowerCase().includes(search.toLowerCase()) &&
      (source === 'all' || model.source === source)
  )
  const references =
    error instanceof ApiError && error.status === 409
      ? error.references
      : undefined
  function importModels(modelIds: string[]) {
    importTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    setImportIds(modelIds)
  }
  function restoreImportFocus() {
    importTrigger.current?.focus()
  }
  async function refresh() {
    changed(await api<Detail>(channelPath(channel.id)))
  }
  async function openLinkedModel(id: string) {
    editorTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    setBusy(true)
    setError(null)
    try {
      setModelEditor(await api<Model>('/llm/models/' + id))
    } catch (cause) {
      setError(cause)
      if (cause instanceof ApiError && cause.status === 403)
        setPermissionLost(true)
    } finally {
      setBusy(false)
    }
  }
  async function discover() {
    if (!modelDiscovery) return
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      const result = await api<Discovery>(
        channelPath(channel.id) + '/discover',
        'POST',
        { version: channel.version },
        csrf
      )
      changed(result.channel)
      if (!result.ok) {
        setError(new Error(result.message))
        return
      }
      setSelected((previous) =>
        previous.filter((id) =>
          result.candidates?.some((model) => model.id === id)
        )
      )
    } catch (e) {
      setError(e)
      if (e instanceof ApiError && e.status === 403) setPermissionLost(true)
    } finally {
      setBusy(false)
    }
  }
  async function save(
    modelIds: string[],
    snapshot?: string | null,
    remove = false,
    configure = false
  ) {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      const updated = await api<Detail>(
        channelPath(channel.id) + '/models',
        remove ? 'DELETE' : 'POST',
        {
          version: channel.version,
          models: modelIds.map((id) => ({ id })),
          snapshot_id: snapshot,
        },
        csrf
      )
      changed(updated)
      setSelected([])
      setRegisteredSelection((previous) =>
        previous.filter((id) => !modelIds.includes(id))
      )
      setRemoveId(null)
      form.reset()
      setNotice(remove ? '已移除模型登记' : '模型已登记，可继续添加')
      if (configure) {
        if (modelIds.length === 1) {
          importTrigger.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null
          setCreateSource({ channel: updated, upstream: modelIds[0] })
        } else importModels(modelIds)
      }
    } catch (e) {
      setError(e)
      if (e instanceof ApiError && e.status === 403) setPermissionLost(true)
      if (remove && e instanceof ApiError && e.status === 409) setRemoveId(null)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className='flex min-w-0 flex-col gap-5'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='font-medium'>上游模型</p>
        <div className='flex flex-wrap gap-2'>
          {modelDiscovery && (
            <Button
              variant='outline'
              size='sm'
              disabled={disabled}
              onClick={() => void discover()}
            >
              <Download />
              {busy ? '正在获取…' : preview ? '重新获取' : '从上游获取'}
            </Button>
          )}
          <Button
            size='sm'
            disabled={disabled || !channel.models.length}
            onClick={() =>
              importModels(
                registeredSelection.length
                  ? registeredSelection
                  : channel.models.map((model) => model.id)
              )
            }
          >
            批量导入平台模型
          </Button>
        </div>
      </div>
      {!modelDiscovery && (
        <Alert>
          <AlertTitle>需要提供模型 ID</AlertTitle>
          <AlertDescription>请手动填写模型 ID。</AlertDescription>
        </Alert>
      )}
      {!!error && <RequestError error={error} />}
      {!!references?.length && (
        <Alert>
          <AlertTitle>模型仍被启用绑定引用，不能移除</AlertTitle>
          <AlertDescription className='flex flex-col gap-2'>
            {references.map((reference) => (
              <div
                key={reference.binding_id}
                className='flex flex-wrap items-center gap-2'
              >
                <span>
                  {reference.model_name} · {reference.operation}
                </span>
                <Button
                  type='button'
                  variant='link'
                  size='sm'
                  disabled={permissionLost}
                  onClick={() => void openLinkedModel(reference.model_id)}
                >
                  查看关联模型
                </Button>
              </div>
            ))}
          </AlertDescription>
        </Alert>
      )}
      {notice && (
        <p role='status' className='text-sm'>
          {notice}
        </p>
      )}
      {preview && (
        <div className='flex min-w-0 flex-col gap-3 rounded-md border p-4'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <p className='font-medium'>上游返回的模型</p>
            <Badge variant='secondary'>{candidates.length} 个待登记</Badge>
          </div>
          <p className='text-xs text-muted-foreground'>
            更新于 {dateTime(preview.fetched_at)}
          </p>
          {preview.partial && (
            <Alert>
              <AlertTitle>已获取部分目录</AlertTitle>
              <AlertDescription>
                目录还有更多结果，当前结果已保留。可缩小上游目录范围后重新获取。
              </AlertDescription>
            </Alert>
          )}
          {candidates.length ? (
            <>
              <Input
                aria-label='搜索上游返回的模型'
                placeholder='搜索模型 ID'
                value={previewSearch}
                onChange={(event) => setPreviewSearch(event.target.value)}
              />
              <div className='max-h-60 overflow-y-auto'>
                {matches.map((model) => (
                  <SelectionRow key={model.id}>
                    <Checkbox
                      disabled={disabled}
                      checked={selected.includes(model.id)}
                      onCheckedChange={(checked) =>
                        setSelected((previous) =>
                          checked
                            ? [...previous, model.id]
                            : previous.filter((id) => id !== model.id)
                        )
                      }
                    />
                    <span className='min-w-0 font-mono text-sm break-all'>
                      {model.id}
                    </span>
                  </SelectionRow>
                ))}
                {!matches.length && (
                  <p className='p-3 text-sm text-muted-foreground'>
                    没有匹配的模型
                  </p>
                )}
              </div>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <Button
                  variant='ghost'
                  size='sm'
                  disabled={disabled}
                  onClick={() =>
                    setSelected((previous) =>
                      allMatchedSelected
                        ? previous.filter(
                            (id) => !matches.some((model) => model.id === id)
                          )
                        : [
                            ...new Set([
                              ...previous,
                              ...matches.map((model) => model.id),
                            ]),
                          ]
                    )
                  }
                >
                  {allMatchedSelected
                    ? '取消全选'
                    : previewSearch
                      ? '全选匹配结果'
                      : '选择全部'}
                </Button>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={disabled || selected.length === 0}
                  onClick={() => void save(selected, preview.snapshot_id)}
                >
                  仅登记（{selected.length}）
                </Button>
                <Button
                  size='sm'
                  disabled={disabled || selected.length === 0}
                  onClick={() =>
                    void save(selected, preview.snapshot_id, false, true)
                  }
                >
                  登记并配置（{selected.length}）
                </Button>
              </div>
            </>
          ) : (
            <p className='text-sm text-muted-foreground'>
              {preview.candidates?.length
                ? '返回的模型均已登记。'
                : '上游返回了空目录，你也可以手动登记模型。'}
            </p>
          )}
        </div>
      )}
      {!channel.archived && (
        <CollapsibleSection title='手动登记模型' defaultOpen={!modelDiscovery}>
          <Form {...form}>
            <form
              className='flex flex-col gap-3'
              onSubmit={(event) =>
                void form.handleSubmit((values) => save(ids(values.models)))(
                  event
                )
              }
            >
              <FormField
                control={form.control}
                name='models'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>模型 ID</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        placeholder={'model-id\n另一个-model-id'}
                        disabled={disabled}
                        rows={3}
                      />
                    </FormControl>
                    <FormDescription>
                      每行或用逗号分隔一个模型 ID；重复项会合并。
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button className='self-end' size='sm' disabled={disabled}>
                <Plus />
                登记模型
              </Button>
            </form>
          </Form>
        </CollapsibleSection>
      )}
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='text-sm font-medium'>已登记（{channel.models.length}）</p>
        <div className='flex items-center gap-2'>
          <Search className='size-4 text-muted-foreground' />
          <Input
            aria-label='搜索已登记模型'
            placeholder='搜索模型 ID'
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className='w-44'
          />
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger aria-label='筛选模型来源' className='w-32'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value='all'>全部来源</SelectItem>
                <SelectItem value='manual'>手动</SelectItem>
                <SelectItem value='discovery'>发现</SelectItem>
                <SelectItem value='configuration'>渠道配置</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>
      {!!registeredSelection.length && (
        <div className='flex flex-wrap items-center gap-2'>
          <span className='text-sm'>已选 {registeredSelection.length} 项</span>
          <Button
            size='sm'
            disabled={disabled}
            onClick={() => importModels(registeredSelection)}
          >
            导入选中模型
          </Button>
          <Button
            size='sm'
            variant='ghost'
            onClick={() => setRegisteredSelection([])}
          >
            清除选择
          </Button>
        </div>
      )}
      <div className='flex flex-col gap-3 sm:hidden'>
        {visible.map((model) => (
          <div
            key={model.id}
            className='flex min-w-0 flex-col gap-3 rounded-md border p-3'
          >
            <div className='flex min-w-0 items-start gap-2'>
              <Checkbox
                aria-label={`选择 ${model.id}`}
                checked={registeredSelection.includes(model.id)}
                onCheckedChange={(checked) =>
                  setRegisteredSelection((previous) =>
                    checked
                      ? [...previous, model.id]
                      : previous.filter((id) => id !== model.id)
                  )
                }
              />
              <span className='min-w-0 font-mono text-sm break-all'>
                {model.id}
              </span>
            </div>
            <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
              <Badge variant='outline'>
                {
                  {
                    manual: '手动',
                    discovery: '发现',
                    configuration: '渠道配置',
                  }[model.source]
                }
              </Badge>
              {dateTime(model.registered_at)}
            </div>
            {bindingReferences
              .filter((reference) => reference.upstream_model_id === model.id)
              .map((reference) => (
                <Button
                  key={reference.binding_id}
                  type='button'
                  variant='link'
                  size='sm'
                  disabled={permissionLost}
                  className='h-auto justify-start p-0'
                  onClick={() => void openLinkedModel(reference.model_id)}
                >
                  {reference.model_name} · {reference.operation}
                </Button>
              ))}
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                size='sm'
                variant='outline'
                disabled={disabled}
                onClick={() => importModels([model.id])}
              >
                导入
              </Button>
              <Button
                type='button'
                size='sm'
                variant='ghost'
                disabled={disabled}
                onClick={() => setRemoveId(model.id)}
              >
                移除
              </Button>
            </div>
          </div>
        ))}
        {!visible.length && (
          <p className='rounded-md border p-4 text-center text-sm text-muted-foreground'>
            {search || source !== 'all' ? '没有匹配的模型' : '尚未登记模型'}
          </p>
        )}
      </div>
      <div className='hidden min-w-0 overflow-hidden rounded-md border sm:block'>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <span className='sr-only'>选择</span>
              </TableHead>
              <TableHead>模型 ID</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>关联模型</TableHead>
              <TableHead>
                <span className='sr-only'>操作</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((model) => (
              <TableRow key={model.id}>
                <TableCell>
                  <Checkbox
                    aria-label={`选择 ${model.id}`}
                    checked={registeredSelection.includes(model.id)}
                    onCheckedChange={(checked) =>
                      setRegisteredSelection((previous) =>
                        checked
                          ? [...previous, model.id]
                          : previous.filter((id) => id !== model.id)
                      )
                    }
                  />
                </TableCell>
                <TableCell className='max-w-64 font-mono break-all'>
                  {model.id}
                </TableCell>
                <TableCell>
                  <Badge variant='outline'>
                    {
                      {
                        manual: '手动',
                        discovery: '发现',
                        configuration: '渠道配置',
                      }[model.source]
                    }
                  </Badge>
                  <span className='block text-xs text-muted-foreground'>
                    {dateTime(model.registered_at)}
                  </span>
                </TableCell>
                <TableCell>
                  {bindingReferences.filter(
                    (reference) => reference.upstream_model_id === model.id
                  ).length ? (
                    <div className='flex flex-col gap-1'>
                      {bindingReferences
                        .filter(
                          (reference) =>
                            reference.upstream_model_id === model.id
                        )
                        .map((reference) => (
                          <Button
                            key={reference.binding_id}
                            type='button'
                            variant='link'
                            size='sm'
                            disabled={permissionLost}
                            className='h-auto justify-start p-0'
                            onClick={() =>
                              void openLinkedModel(reference.model_id)
                            }
                          >
                            {reference.model_name} · {reference.operation}
                          </Button>
                        ))}
                    </div>
                  ) : (
                    <span className='text-muted-foreground'>无</span>
                  )}
                </TableCell>
                <TableCell>
                  <Button
                    type='button'
                    size='sm'
                    variant='ghost'
                    disabled={disabled}
                    onClick={() => importModels([model.id])}
                  >
                    导入
                  </Button>
                  <Button
                    size='icon'
                    variant='ghost'
                    aria-label={`移除 ${model.id}`}
                    disabled={disabled}
                    onClick={() => setRemoveId(model.id)}
                  >
                    <Trash2 />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!visible.length && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className='h-24 text-center text-muted-foreground'
                >
                  {search || source !== 'all'
                    ? '没有匹配的模型'
                    : '尚未登记模型'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <ConfirmDialog
        open={removeId !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setRemoveId(null)
        }}
        title='移除上游模型登记？'
        desc={`仅移除本渠道库存中的 ${removeId ?? ''}；已启用绑定引用时服务端会阻止移除。`}
        cancelBtnText='取消'
        confirmText={busy ? '处理中…' : '移除登记'}
        isLoading={busy}
        handleConfirm={() => {
          if (removeId) void save([removeId], null, true)
        }}
      />
      {importIds && (
        <ModelImport
          initialSource={channel}
          initialIds={importIds}
          close={() => setImportIds(null)}
          restoreFocus={restoreImportFocus}
          configure={(model) => {
            editorTrigger.current = importTrigger.current
            setImportIds(null)
            setModelEditor(model)
          }}
        />
      )}
      {createSource && (
        <ModelCreate
          initialChannel={createSource.channel}
          initialUpstream={createSource.upstream}
          close={() => setCreateSource(null)}
          restoreFocus={restoreImportFocus}
          saved={() => {
            setCreateSource(null)
            void refresh()
          }}
        />
      )}
      {modelEditor && (
        <ModelEditor
          model={modelEditor}
          close={() => {
            setModelEditor(null)
            editorTrigger.current?.focus()
          }}
          saved={() => {
            setModelEditor(null)
            void refresh()
            editorTrigger.current?.focus()
          }}
        />
      )}
    </div>
  )
}
