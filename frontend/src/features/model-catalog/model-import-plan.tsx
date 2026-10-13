import { useDeferredValue, useEffect, useState } from 'react'
import { z } from 'zod'
import { useForm, useWatch, type UseFormReturn } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
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
import { RequestError, LoadingState } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { kinds, type Model } from './model-form'

const rowSchema = z
  .object({
    upstream_id: z.string(),
    action: z.enum(['create', 'link', 'skip']),
    slug: z.string().max(200, '最多 200 个字符'),
    name: z.string().max(100, '最多 100 个字符'),
    kinds: z.array(
      z.enum([
        'chat',
        'embedding',
        'rerank',
        'image_generation',
        'speech',
        'transcription',
      ])
    ),
    target_id: z.string().nullable(),
  })
  .superRefine((row, context) => {
    if (row.action === 'create') {
      if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/.test(row.slug))
        context.addIssue({
          code: 'custom',
          path: ['slug'],
          message: '请输入有效技术名称',
        })
      if (!row.name.trim())
        context.addIssue({
          code: 'custom',
          path: ['name'],
          message: '请输入展示名称',
        })
    }
    if (row.action === 'link') {
      if (!row.target_id)
        context.addIssue({
          code: 'custom',
          path: ['target_id'],
          message: '请选择目标模型',
        })
      if (!row.kinds.length)
        context.addIssue({
          code: 'custom',
          path: ['kinds'],
          message: '请选择目标模型已有的接口',
        })
    }
  })
const planSchema = z.object({ items: z.array(rowSchema).min(1).max(50) })
type PlanValues = z.infer<typeof planSchema>
export type ImportRows = PlanValues['items']

export function ImportPlan({
  preview,
  disabled,
  onEdit,
  onPreview,
  onPermissionLost,
}: {
  preview: Schema['ImportPreview']
  disabled: boolean
  onEdit: () => void
  onPreview: (rows: ImportRows) => void
  onPermissionLost: (lost: boolean) => void
}) {
  const form = useForm<PlanValues>({
    resolver: zodResolver(planSchema),
    defaultValues: {
      items: preview.items.map((row) => ({
        upstream_id: row.upstream_id,
        action: row.action ?? 'create',
        slug: row.slug ?? row.upstream_id,
        name: row.name ?? row.upstream_id.slice(0, 100),
        kinds: row.kinds ?? [],
        target_id: row.target_id ?? null,
      })),
    },
  })
  return (
    <Form {...form}>
      <form
        className='flex flex-col gap-4'
        onSubmit={form.handleSubmit((values) => onPreview(values.items))}
      >
        {preview.items.map((row, index) => (
          <ImportRow
            key={row.upstream_id}
            row={row}
            index={index}
            form={form}
            disabled={disabled}
            onEdit={onEdit}
            onPermissionLost={onPermissionLost}
          />
        ))}
        <div className='flex justify-end'>
          <Button variant='outline' disabled={disabled} type='submit'>
            更新预览
          </Button>
        </div>
      </form>
    </Form>
  )
}

function ImportRow({
  row,
  index,
  form,
  disabled,
  onEdit,
  onPermissionLost,
}: {
  row: Schema['ImportPreviewItem']
  index: number
  form: UseFormReturn<PlanValues>
  disabled: boolean
  onEdit: () => void
  onPermissionLost: (lost: boolean) => void
}) {
  const value = useWatch({ control: form.control, name: `items.${index}` })
  const [target, setTarget] = useState<Model | null>(null)
  const options = row.hint.available_kinds.filter(
    (kind) =>
      !target || (target.operations ?? []).some((op) => op.kind === kind)
  )
  const unsupported = !!row.hint.mode && !row.hint.kind
  return (
    <fieldset
      disabled={disabled}
      className='min-w-0 space-y-4 rounded-lg border p-4'
    >
      <legend className='max-w-full px-1 break-all'>{row.upstream_id}</legend>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge variant='outline'>
          {row.hint.kind
            ? '资料参考：' + kinds[row.hint.kind]
            : unsupported
              ? '接口暂不可用'
              : '类型未知'}
        </Badge>
        {row.status === 'unchanged' && (
          <Badge variant='secondary'>关联已存在</Badge>
        )}
        {(row.errors ?? []).map((error) => (
          <p key={error} role='alert' className='text-sm text-destructive'>
            {error}
          </p>
        ))}
      </div>
      <div className='grid gap-4 sm:grid-cols-2'>
        <FormField
          control={form.control}
          name={`items.${index}.action`}
          render={({ field }) => (
            <FormItem>
              <FormLabel>处理方式</FormLabel>
              <Select
                value={field.value}
                disabled={disabled}
                onValueChange={(v) => {
                  field.onChange(v)
                  onEdit()
                  setTarget(null)
                  form.setValue(`items.${index}.target_id`, null)
                }}
              >
                <FormControl>
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value='create'>新建模型</SelectItem>
                    <SelectItem value='link'>关联现有模型</SelectItem>
                    <SelectItem value='skip'>跳过</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        {value.action !== 'skip' && (
          <FormField
            control={form.control}
            name={`items.${index}.kinds`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>接口类型</FormLabel>
                <Select
                  value={field.value[0] ?? 'later'}
                  disabled={disabled || unsupported}
                  onValueChange={(v) => {
                    field.onChange(v === 'later' ? [] : [v])
                    onEdit()
                  }}
                >
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='later'>
                        {value.action === 'create'
                          ? '稍后配置'
                          : '选择已有接口'}
                      </SelectItem>
                      {options.map((kind) => (
                        <SelectItem key={kind} value={kind}>
                          {kinds[kind]}
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
        {value.action === 'create' && (
          <>
            <FormField
              control={form.control}
              name={`items.${index}.slug`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>技术名称</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      onChange={(e) => {
                        field.onChange(e)
                        onEdit()
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name={`items.${index}.name`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>展示名称</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      onChange={(e) => {
                        field.onChange(e)
                        onEdit()
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </>
        )}
        {value.action === 'link' && (
          <div className='sm:col-span-2'>
            <TargetPicker
              disabled={disabled}
              form={form}
              index={index}
              onSelect={(model) => {
                setTarget(model)
                onEdit()
                form.setValue(`items.${index}.kinds`, [])
              }}
              onPermissionLost={onPermissionLost}
            />
          </div>
        )}
      </div>
    </fieldset>
  )
}

function TargetPicker({
  disabled,
  form,
  index,
  onSelect,
  onPermissionLost,
}: {
  disabled: boolean
  form: UseFormReturn<PlanValues>
  index: number
  onSelect: (target: Model | null) => void
  onPermissionLost: (lost: boolean) => void
}) {
  const { organization } = useOrganization()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const q = useDeferredValue(search)
  const params = new URLSearchParams({
    q,
    state: 'current',
    page: String(page),
  }).toString()
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, 'model-catalog', params],
    queryFn: ({ signal }) =>
      api<Schema['CatalogPage']>(
        '/llm/models?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  useEffect(() => {
    if (query.error instanceof ApiError && query.error.status === 403)
      onPermissionLost(true)
  }, [query.error, onPermissionLost])
  function clear() {
    form.setValue(`items.${index}.target_id`, null)
    onSelect(null)
  }
  return (
    <div className='space-y-3'>
      <Input
        aria-label='搜索目标模型'
        placeholder='搜索名称或技术名称'
        value={search}
        disabled={disabled}
        onChange={(e) => {
          setSearch(e.target.value)
          setPage(1)
          clear()
        }}
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError
          error={query.error}
          retry={
            query.error instanceof ApiError && query.error.status === 403
              ? undefined
              : () => void query.refetch()
          }
        />
      ) : (
        <>
          <FormField
            control={form.control}
            name={`items.${index}.target_id`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>目标模型</FormLabel>
                <Select
                  value={field.value ?? ''}
                  disabled={disabled}
                  onValueChange={(id) => {
                    field.onChange(id)
                    onSelect(
                      query.data.items.find((model) => model.id === id) ?? null
                    )
                  }}
                >
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue placeholder='选择目标模型' />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      {query.data.items.map((model) => (
                        <SelectItem key={model.id} value={model.id}>
                          {model.name} · {model.slug}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          {!query.data.items.length && (
            <p className='text-sm text-muted-foreground'>没有匹配的模型</p>
          )}
          {query.data.total > 20 && (
            <div className='flex items-center justify-between gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={disabled || page === 1}
                onClick={() => {
                  setPage(page - 1)
                  clear()
                }}
              >
                上一页目标
              </Button>
              <span className='text-sm'>第 {page} 页</span>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={disabled || page * 20 >= query.data.total}
                onClick={() => {
                  setPage(page + 1)
                  clear()
                }}
              >
                下一页目标
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
