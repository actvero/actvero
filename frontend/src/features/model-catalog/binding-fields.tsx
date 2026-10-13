import { useState } from 'react'
import { useFieldArray, useFormContext, useWatch } from 'react-hook-form'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  ChannelModelPicker,
  type ChannelModelSource,
} from './channel-model-picker'
import {
  priceValues,
  routeStates,
  type Model,
  type ModelValues,
} from './model-form'
import { RoutingFields, BindingRoutingFields } from './routing-fields'

type Candidate = {
  channel_id: string
  channel_name: string
  channel_version: number
  upstream_id: string
  manual_enabled: boolean
  operations: string[]
}
type CandidatePage = {
  items: Candidate[]
  total: number
  page: number
  page_size: number
}
type Match = 'exact' | 'prefix' | 'suffix' | 'contains'

function newBinding(
  channel_id: string,
  upstream_id: string
): ModelValues['bindings'][number] {
  return {
    binding_id: null,
    channel_id,
    upstream_id,
    price: priceValues(),
    enabled: false,
    priority: '0',
    weight: '100',
    compatibility_key: '',
    chat_options: {
      reasoning_format: 'openai',
      output_parameter: 'max_completion_tokens',
    },
  }
}

export function BindingFields({
  model,
  disabled,
  names,
  remember,
}: {
  model?: Model
  disabled: boolean
  names: Record<string, string>
  remember: (id: string, name: string) => void
}) {
  const form = useFormContext<ModelValues>()
  const [publicSlug, kind, mode] = useWatch({
    control: form.control,
    name: ['slug', 'kind', 'routing.mode'],
  })
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: 'bindings',
  })
  const { organization } = useOrganization()
  const [adding, setAdding] = useState(false)
  const [source, setSource] = useState<ChannelModelSource | null>(null)
  const [match, setMatch] = useState<Match>('exact')
  const [scanned, setScanned] = useState<{
    q: string
    match: Match
    kind: string
  } | null>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string[]>([])
  const health = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-routes',
      model?.id,
      model?.version,
    ],
    enabled: !!model,
    queryFn: ({ signal }) =>
      api<Schema['RouteStateView'][]>(
        `/llm/models/${model!.id}/routes`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const candidates = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-candidates',
      scanned,
      page,
    ],
    enabled: !!scanned,
    queryFn: ({ signal }) =>
      api<CandidatePage>(
        `/llm/model-candidates?${new URLSearchParams({ q: scanned!.q, match: scanned!.match, kind: scanned!.kind, page: String(page) })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const duplicate = (channel: string, upstream: string) =>
    fields.some((b) => b.channel_id === channel && b.upstream_id === upstream)
  const sourceDuplicate =
    !!source && duplicate(source.channel.id, source.upstream)
  function addSource() {
    if (!source || sourceDuplicate || fields.length >= 50) return
    remember(source.channel.id, source.channel.name)
    append(newBinding(source.channel.id, source.upstream))
    setSource(null)
    setAdding(false)
  }
  function confirmCandidates() {
    const additions =
      candidates.data?.items.filter(
        (candidate) =>
          selected.includes(
            `${candidate.channel_id}|${candidate.upstream_id}`
          ) && !duplicate(candidate.channel_id, candidate.upstream_id)
      ) ?? []
    if (fields.length + additions.length > 50) return
    for (const candidate of additions) {
      remember(candidate.channel_id, candidate.channel_name)
      append(newBinding(candidate.channel_id, candidate.upstream_id))
    }
    setSelected([])
    setScanned(null)
  }
  return (
    <div className='flex min-w-0 flex-col gap-6'>
      <RoutingFields names={names} />
      {mode === 'auto' && (
        <Card>
          <CardHeader>
            <CardTitle>查找候选渠道</CardTitle>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            <p className='text-sm text-muted-foreground'>
              以技术名称 {publicSlug || '（请先填写）'}{' '}
              搜索当前组织已登记的上游模型。找到的来源只进入预览，确认后加入草稿且默认停用；新库存不会自动扩大调用范围。
            </p>
            <div className='flex flex-wrap items-end gap-3'>
              <div className='flex min-w-40 flex-col gap-2'>
                <Label htmlFor='candidate-match'>匹配方式</Label>
                <Select
                  value={match}
                  onValueChange={(value) => {
                    setMatch(value as Match)
                    setScanned(null)
                    setSelected([])
                  }}
                  disabled={disabled}
                >
                  <SelectTrigger id='candidate-match'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='exact'>完全匹配</SelectItem>
                      <SelectItem value='prefix'>前缀</SelectItem>
                      <SelectItem value='suffix'>后缀</SelectItem>
                      <SelectItem value='contains'>包含</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
              <Button
                type='button'
                variant='outline'
                disabled={disabled || !publicSlug}
                onClick={() => {
                  setPage(1)
                  setSelected([])
                  setScanned({ q: publicSlug, match, kind })
                }}
              >
                查找候选
              </Button>
            </div>
            {scanned &&
              (candidates.isPending || candidates.isFetching ? (
                <p role='status'>查找中…</p>
              ) : candidates.isError ? (
                <RequestError
                  error={candidates.error}
                  retry={() => void candidates.refetch()}
                />
              ) : (
                <>
                  <p className='text-sm'>
                    找到 {candidates.data.total}{' '}
                    条候选。名称匹配不证明型号、兼容性或健康状态。
                  </p>
                  {candidates.data.items.length === 0 && (
                    <p role='status' className='text-sm text-muted-foreground'>
                      没有匹配来源。仍可手动添加渠道关联。
                    </p>
                  )}
                  <div className='flex max-h-64 flex-col gap-2 overflow-y-auto'>
                    {candidates.data.items.map((candidate) => {
                      const key = `${candidate.channel_id}|${candidate.upstream_id}`
                      const exists = duplicate(
                        candidate.channel_id,
                        candidate.upstream_id
                      )
                      const unavailable = !candidate.operations.includes(kind)
                      return (
                        <label
                          key={key}
                          className='flex items-start gap-3 rounded-md border p-3 text-sm'
                        >
                          <Checkbox
                            className='mt-1'
                            aria-label={`选择候选 ${candidate.channel_name} / ${candidate.upstream_id}`}
                            checked={selected.includes(key)}
                            disabled={disabled || exists || unavailable}
                            onCheckedChange={(checked) =>
                              setSelected((before) =>
                                checked
                                  ? [...before, key]
                                  : before.filter((item) => item !== key)
                              )
                            }
                          />
                          <span className='min-w-0 break-all'>
                            {candidate.channel_name} / {candidate.upstream_id}
                            <span className='block text-muted-foreground'>
                              {exists
                                ? '已关联'
                                : !candidate.manual_enabled
                                  ? '渠道已停用，关联后仍不可调用'
                                  : !candidate.operations.includes(kind)
                                    ? '接口不适配'
                                    : '尚未绑定，加入后待测试'}
                            </span>
                          </span>
                        </label>
                      )
                    })}
                  </div>
                  {candidates.data.total > page * candidates.data.page_size && (
                    <Button
                      type='button'
                      variant='outline'
                      onClick={() => {
                        setPage(page + 1)
                        setSelected([])
                      }}
                    >
                      下一页候选
                    </Button>
                  )}
                  {page > 1 && (
                    <Button
                      type='button'
                      variant='outline'
                      onClick={() => {
                        setPage(page - 1)
                        setSelected([])
                      }}
                    >
                      上一页候选
                    </Button>
                  )}
                  <Button
                    type='button'
                    className='self-start'
                    disabled={
                      disabled ||
                      selected.length === 0 ||
                      fields.length + selected.length > 50
                    }
                    onClick={confirmCandidates}
                  >
                    确认关联 {selected.length} 条到草稿
                  </Button>
                </>
              ))}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader className='flex flex-row flex-wrap items-center justify-between gap-3'>
          <CardTitle>渠道与模型映射 · {fields.length}</CardTitle>
          <Button
            type='button'
            variant='outline'
            disabled={disabled || fields.length >= 50}
            onClick={() => setAdding(true)}
          >
            <Plus />
            添加渠道关联
          </Button>
        </CardHeader>
        <CardContent className='flex flex-col gap-3'>
          {health.isError && (
            <RequestError
              error={health.error}
              retry={() => void health.refetch()}
            />
          )}
          {!fields.length && (
            <p className='text-sm text-muted-foreground'>
              尚未关联渠道。模型调用接口需要已确认的上游映射。
            </p>
          )}
          {fields.map((binding, index) => {
            const state = model?.binding_states.find((item) =>
              binding.binding_id
                ? item.binding_id === binding.binding_id
                : item.channel_id === binding.channel_id &&
                  item.upstream_id === binding.upstream_id
            )
            const route = (Array.isArray(health.data) ? health.data : [])
              .filter((item) => !item.operation || item.operation === kind)
              .find(
                (item) =>
                  item.channel_id === binding.channel_id &&
                  item.upstream_id === binding.upstream_id
              )
            return (
              <div
                key={binding.id}
                className='flex min-w-0 flex-col gap-3 rounded-lg border p-4'
              >
                <div className='flex min-w-0 flex-wrap items-center gap-3'>
                  <div className='min-w-0 flex-1'>
                    <p className='font-medium break-all'>
                      {names[binding.channel_id] ??
                        state?.channel_name ??
                        '已选渠道'}{' '}
                      / {binding.upstream_id}
                    </p>
                    <p className='text-sm break-all text-muted-foreground'>
                      技术名称 {publicSlug || '未填写'} → 上游模型名称{' '}
                      {binding.upstream_id}
                    </p>
                  </div>
                  <Badge
                    variant={
                      state && state.state !== 'registered'
                        ? 'destructive'
                        : 'outline'
                    }
                  >
                    {state && state.state !== 'registered'
                      ? state.state === 'archived'
                        ? '渠道已归档'
                        : '上游模型已移除'
                      : form.formState.isDirty
                        ? '保存后检查'
                        : (routeStates[route?.state ?? 'unverified'] ??
                          '待测试')}
                  </Badge>
                  <label className='flex items-center gap-2 text-sm'>
                    <Switch
                      checked={form.watch(`bindings.${index}.enabled`)}
                      disabled={disabled}
                      onCheckedChange={(enabled) =>
                        form.setValue(`bindings.${index}.enabled`, enabled, {
                          shouldDirty: true,
                        })
                      }
                    />
                    启用渠道
                  </label>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    aria-label={`移除关联 ${binding.upstream_id}`}
                    disabled={disabled}
                    onClick={() => remove(index)}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <CollapsibleSection title='配置参数与兼容确认'>
                  <BindingRoutingFields
                    index={index}
                    dirty={form.formState.isDirty}
                    state={route?.state}
                    hideEnabled
                  />
                </CollapsibleSection>
              </div>
            )
          })}
        </CardContent>
      </Card>
      <Dialog
        open={adding}
        onOpenChange={(open) => {
          setAdding(open)
          if (!open) setSource(null)
        }}
      >
        <DialogContent
          className='max-h-[90vh] overflow-y-auto'
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle>添加渠道关联</DialogTitle>
            <DialogDescription>
              选择已登记渠道和上游模型，预览映射后加入草稿。整页保存后才生效，新增关联默认停用。
            </DialogDescription>
          </DialogHeader>
          <ChannelModelPicker disabled={disabled} onChange={setSource} />
          {source && (
            <div className='rounded-md border p-3 text-sm break-all'>
              技术名称 {publicSlug || '未填写'} → {source.channel.name} →
              上游模型名称 {source.upstream}
              {sourceDuplicate && (
                <span className='block text-muted-foreground'>
                  此关联已存在。
                </span>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              onClick={() => setAdding(false)}
            >
              取消
            </Button>
            <Button
              type='button'
              disabled={
                disabled || !source || sourceDuplicate || fields.length >= 50
              }
              onClick={addSource}
            >
              加入草稿
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
