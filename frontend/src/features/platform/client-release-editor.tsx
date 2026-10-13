import { useEffect, useState } from 'react'
import { z } from 'zod'
import {
  useFieldArray,
  useForm,
  useWatch,
  type FieldPath,
} from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import {
  architectureNames,
  architectureLabel,
  platformNames,
  targetName,
  type Asset,
  type Recommendation,
  type Release,
} from '@/features/client-downloads/data'

const assetSchema = z
  .object({
    platform: z.enum(['windows', 'macos']),
    architecture: z.enum(['x64', 'arm64', 'universal']),
    url: z
      .string()
      .max(2048)
      .refine(
        (v) =>
          !v ||
          (() => {
            try {
              const u = new URL(v)
              return (
                u.protocol === 'https:' &&
                !!u.hostname &&
                !u.username &&
                !u.password &&
                !u.hash &&
                !/[\s<>"\\]/.test(v)
              )
            } catch {
              return false
            }
          })(),
        '请填写不含账号、密码和片段的 HTTPS 链接'
      ),
    filename: z.string().max(180),
    minimum_os: z.string().max(100),
    size_bytes: z.number().int().positive().max(20_000_000_000).nullable(),
    sha256: z
      .string()
      .refine(
        (v) => !v || /^[a-fA-F0-9]{64}$/.test(v),
        'SHA256 须为 64 位十六进制'
      ),
  })
  .refine((a) => a.platform !== 'windows' || a.architecture !== 'universal', {
    message: 'Windows 请选 x64 或 ARM64',
    path: ['architecture'],
  })
const schema = z.object({
  expected_revision: z.number().int().min(0),
  version: z
    .string()
    .trim()
    .min(1, '请填写版本号')
    .max(50)
    .regex(
      /^[a-zA-Z0-9][a-zA-Z0-9._+-]*$/,
      '版本号只能包含字母、数字、点、横线、下划线和加号'
    ),
  release_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, '请选择发布日期'),
  notes: z.string().max(12000),
  assets: z
    .array(assetSchema)
    .max(5)
    .refine(
      (assets) => new Set(assets.map(targetName)).size === assets.length,
      '同一系统和架构只能有一个安装包'
    ),
})
type Draft = z.infer<typeof schema>
const emptyAsset: Draft['assets'][number] = {
  platform: 'windows',
  architecture: 'x64',
  url: '',
  filename: '',
  minimum_os: '',
  size_bytes: null,
  sha256: '',
}
const values = (saved: Release | null): Draft =>
  saved
    ? {
        expected_revision: saved.revision,
        version: saved.version,
        release_date: saved.release_date,
        notes: saved.notes,
        assets: saved.assets.map((a) => ({
          ...emptyAsset,
          ...a,
          size_bytes: a.size_bytes ?? null,
        })),
      }
    : {
        expected_revision: 0,
        version: '',
        release_date: new Date().toLocaleDateString('en-CA'),
        notes: '',
        assets: [],
      }
const actions = {
  created: '新建草稿',
  saved: '保存',
  published: '发布',
  withdrawn: '下架',
  recommended: '推荐',
  deleted: '删除草稿',
} as const

export function ClientReleaseEditor({
  saved,
  recommendations,
  onClose,
  onChanged,
  onDenied,
}: {
  saved: Release | null
  recommendations: Recommendation[]
  onClose: () => void
  onChanged: () => Promise<void>
  onDenied: (error: unknown) => void
}) {
  const { data: session } = useSession()
  const [id] = useState(() => saved?.id ?? crypto.randomUUID())
  const [record, setRecord] = useState(saved)
  const [recommend, setRecommend] = useState(true)
  const [server, setServer] = useState<Release | null>(null)
  const form = useForm<Draft>({
    resolver: zodResolver(schema),
    defaultValues: values(saved),
    mode: 'onChange',
  })
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: 'assets',
  })
  const watchedAssets = useWatch({ control: form.control, name: 'assets' })
  const path = '/platform/downloads/' + id
  const events = useQuery({
    queryKey: ['platform', 'release-events', path, record?.revision],
    enabled: !!record,
    queryFn: ({ signal }) =>
      api<Schema['ReleaseEventView'][]>(
        path + '/events',
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
  })
  function received(value: Release) {
    setRecord(value)
    form.reset(values(value))
  }
  const mutation = useMutation({
    mutationFn: async ({
      draft,
      publish,
      target,
    }: {
      draft?: Draft
      publish?: boolean
      target?: Asset
    }) => {
      let current = record
      if (draft) {
        current = await api<Release>(path, 'PUT', draft, session?.csrf)
        received(current)
        await onChanged()
      }
      if (!current) throw new Error('请先保存版本')
      if (publish)
        current = await api<Release>(
          path + '/publish',
          'POST',
          { expected_revision: current.revision, recommend },
          session?.csrf
        )
      if (target)
        current = await api<Release>(
          path + '/recommend',
          'POST',
          {
            expected_revision: current.revision,
            platform: target.platform,
            architecture: target.architecture,
          },
          session?.csrf
        )
      return current
    },
    onSuccess: async (value) => {
      received(value)
      toast.success('版本配置已保存')
      await onChanged()
    },
    onError: (error) => {
      if (error instanceof ApiError && [401, 403].includes(error.status))
        onDenied(error)
    },
  })
  const recover = useMutation({
    mutationFn: () => api<Release>(path),
    onSuccess: setServer,
    onError: (error) => {
      if (error instanceof ApiError && [401, 403].includes(error.status))
        onDenied(error)
    },
  })
  const pending = mutation.isPending || recover.isPending
  const immutable = !!record && record.status !== 'draft'
  const eventDenied =
    events.error instanceof ApiError && [401, 403].includes(events.error.status)
  useEffect(() => {
    if (eventDenied) onDenied(events.error)
  }, [eventDenied, events.error, onDenied])
  const forbidden = eventDenied
  const textField = (
    name: FieldPath<Draft>,
    label: string,
    type = 'text',
    disabled = false
  ) => (
    <FormField
      key={name}
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input
              {...field}
              value={
                typeof field.value === 'string' ||
                typeof field.value === 'number'
                  ? field.value
                  : ''
              }
              type={type}
              disabled={pending || forbidden || disabled}
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  )
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose()
      }}
    >
      <DialogContent
        className='flex max-h-[90svh] flex-col sm:max-w-3xl'
        onEscapeKeyDown={(e) => {
          if (pending) e.preventDefault()
        }}
        onInteractOutside={(e) => {
          if (pending) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {record ? '编辑客户端版本' : '新建客户端版本'}
          </DialogTitle>
          <DialogDescription>
            {immutable
              ? '安装包已发布，修改安装包请新建版本；这里可以更新说明。'
              : '保存草稿后，发布才会展示在下载页。'}
          </DialogDescription>
        </DialogHeader>
        {forbidden ? (
          <RequestError error={events.error} />
        ) : (
          <>
            <div className='min-h-0 overflow-y-auto px-1'>
              <Form {...form}>
                <form
                  id='client-release-form'
                  onSubmit={form.handleSubmit((draft) =>
                    mutation.mutate({ draft })
                  )}
                  className='flex flex-col gap-5'
                >
                  <div className='grid gap-4 sm:grid-cols-2'>
                    {textField('version', '版本号', 'text', immutable)}
                    {textField('release_date', '发布日期', 'date', immutable)}
                  </div>
                  <FormField
                    control={form.control}
                    name='notes'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>更新说明</FormLabel>
                        <FormControl>
                          <Textarea {...field} rows={5} disabled={pending} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <h3 className='font-medium'>安装包</h3>
                    {!immutable && (
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        disabled={pending || fields.length >= 5}
                        onClick={() => append({ ...emptyAsset })}
                      >
                        <Plus />
                        添加安装包
                      </Button>
                    )}
                  </div>
                  {form.formState.errors.assets?.message && (
                    <p role='alert' className='text-sm text-destructive'>
                      {form.formState.errors.assets.message}
                    </p>
                  )}
                  {fields.map((item, index) => (
                    <Card key={item.id}>
                      <CardHeader className='flex-row items-center justify-between'>
                        <CardTitle>安装包 {index + 1}</CardTitle>
                        {!immutable && (
                          <Button
                            type='button'
                            variant='ghost'
                            size='icon'
                            aria-label={'移除安装包 ' + (index + 1)}
                            disabled={pending}
                            onClick={() => remove(index)}
                          >
                            <Trash2 />
                          </Button>
                        )}
                      </CardHeader>
                      <CardContent className='flex flex-col gap-4'>
                        <div className='grid gap-4 sm:grid-cols-2'>
                          <FormField
                            control={form.control}
                            name={
                              ('assets.' +
                                index +
                                '.platform') as 'assets.0.platform'
                            }
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel>系统</FormLabel>
                                <Select
                                  value={field.value}
                                  disabled={pending || immutable}
                                  onValueChange={(v) => {
                                    field.onChange(v)
                                    if (
                                      v === 'windows' &&
                                      form.getValues().assets[index]
                                        .architecture === 'universal'
                                    )
                                      form.setValue(
                                        ('assets.' +
                                          index +
                                          '.architecture') as 'assets.0.architecture',
                                        'x64',
                                        {
                                          shouldDirty: true,
                                          shouldValidate: true,
                                        }
                                      )
                                  }}
                                >
                                  <FormControl>
                                    <SelectTrigger>
                                      <SelectValue />
                                    </SelectTrigger>
                                  </FormControl>
                                  <SelectContent>
                                    {Object.entries(platformNames).map(
                                      ([v, label]) => (
                                        <SelectItem key={v} value={v}>
                                          {label}
                                        </SelectItem>
                                      )
                                    )}
                                  </SelectContent>
                                </Select>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                          <FormField
                            control={form.control}
                            name={
                              ('assets.' +
                                index +
                                '.architecture') as 'assets.0.architecture'
                            }
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel>架构</FormLabel>
                                <Select
                                  value={field.value}
                                  disabled={pending || immutable}
                                  onValueChange={field.onChange}
                                >
                                  <FormControl>
                                    <SelectTrigger>
                                      <SelectValue />
                                    </SelectTrigger>
                                  </FormControl>
                                  <SelectContent>
                                    {Object.entries(architectureNames)
                                      .filter(
                                        ([v]) =>
                                          v !== 'universal' ||
                                          watchedAssets?.[index]?.platform ===
                                            'macos'
                                      )
                                      .map(([v]) => (
                                        <SelectItem key={v} value={v}>
                                          {architectureLabel(
                                            watchedAssets?.[index]?.platform ??
                                              'windows',
                                            v as Asset['architecture']
                                          )}
                                        </SelectItem>
                                      ))}
                                  </SelectContent>
                                </Select>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        </div>
                        {textField(
                          ('assets.' + index + '.url') as FieldPath<Draft>,
                          '下载链接（HTTPS）',
                          'url',
                          immutable
                        )}
                        <div className='grid gap-4 sm:grid-cols-2'>
                          {textField(
                            ('assets.' +
                              index +
                              '.filename') as FieldPath<Draft>,
                            '文件名',
                            'text',
                            immutable
                          )}
                          {textField(
                            ('assets.' +
                              index +
                              '.minimum_os') as FieldPath<Draft>,
                            '最低系统要求',
                            'text',
                            immutable
                          )}
                        </div>
                        <FormField
                          control={form.control}
                          name={
                            ('assets.' +
                              index +
                              '.size_bytes') as 'assets.0.size_bytes'
                          }
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>文件大小（字节，可选）</FormLabel>
                              <FormControl>
                                <Input
                                  type='number'
                                  min={1}
                                  step={1}
                                  value={field.value ?? ''}
                                  onChange={(e) =>
                                    field.onChange(
                                      e.target.value === ''
                                        ? null
                                        : e.target.valueAsNumber
                                    )
                                  }
                                  onBlur={field.onBlur}
                                  name={field.name}
                                  ref={field.ref}
                                  disabled={pending || immutable}
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                        {textField(
                          ('assets.' + index + '.sha256') as FieldPath<Draft>,
                          'SHA256（可选）',
                          'text',
                          immutable
                        )}
                        {record?.status === 'published' && (
                          <Button
                            type='button'
                            variant='outline'
                            disabled={
                              pending ||
                              form.formState.isDirty ||
                              recommendations.some(
                                (r) =>
                                  r.release_id === id &&
                                  r.platform ===
                                    record.assets[index].platform &&
                                  r.architecture ===
                                    record.assets[index].architecture
                              )
                            }
                            onClick={() =>
                              mutation.mutate({ target: record.assets[index] })
                            }
                          >
                            设为 {targetName(record.assets[index])} 推荐包
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                  {(!record || record.status !== 'published') && (
                    <div className='flex items-center justify-between gap-3'>
                      <label htmlFor='release-recommend'>
                        发布时设为各架构推荐版本
                      </label>
                      <Switch
                        id='release-recommend'
                        checked={recommend}
                        onCheckedChange={setRecommend}
                        disabled={pending}
                      />
                    </div>
                  )}
                  {mutation.isError && <RequestError error={mutation.error} />}
                  {mutation.isError && (
                    <Button
                      type='button'
                      variant='outline'
                      disabled={pending}
                      onClick={() => recover.mutate()}
                    >
                      读取服务器记录
                    </Button>
                  )}
                  {recover.isError && <RequestError error={recover.error} />}
                  {server && (
                    <Card>
                      <CardHeader>
                        <CardTitle>
                          服务器记录：v{server.version} · 修订 {server.revision}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='flex flex-col gap-3'>
                        <p className='text-sm break-words whitespace-pre-wrap'>
                          {server.notes || '暂无说明'}
                        </p>
                        {server.assets.map((asset) => (
                          <p
                            key={targetName(asset)}
                            className='text-sm break-all'
                          >
                            {targetName(asset)} ·{' '}
                            {asset.filename || '文件名未填写'} ·{' '}
                            {asset.minimum_os || '系统要求未填写'}
                            <br />
                            {asset.url || '链接未填写'}
                          </p>
                        ))}
                        <p className='text-sm text-muted-foreground'>
                          当前草稿仍保留。使用服务器记录会替换本地修改。
                        </p>
                        <Button
                          type='button'
                          variant='outline'
                          onClick={() => {
                            received(server)
                            setServer(null)
                            mutation.reset()
                            recover.reset()
                          }}
                        >
                          使用服务器记录
                        </Button>
                      </CardContent>
                    </Card>
                  )}
                  {events.isError && !eventDenied && (
                    <RequestError
                      error={events.error}
                      retry={() => void events.refetch()}
                    />
                  )}
                  {!!events.data?.length && (
                    <div className='flex flex-col gap-2'>
                      <h3 className='font-medium'>最近操作</h3>
                      {events.data.map((event, i) => (
                        <p key={i} className='text-xs text-muted-foreground'>
                          {event.actor_name} ·{' '}
                          {actions[event.action as keyof typeof actions] ??
                            event.action}{' '}
                          · 修订 {event.revision} ·{' '}
                          {new Date(event.created_at).toLocaleString('zh-CN')}
                        </p>
                      ))}
                    </div>
                  )}
                </form>
              </Form>
            </div>
            <DialogFooter className='flex-wrap'>
              <Button
                type='button'
                variant='outline'
                disabled={pending}
                onClick={onClose}
              >
                关闭
              </Button>
              <Button
                type='submit'
                form='client-release-form'
                disabled={
                  pending ||
                  !form.formState.isValid ||
                  (immutable && !form.formState.isDirty)
                }
              >
                {pending ? '处理中…' : immutable ? '保存说明' : '保存草稿'}
              </Button>
              {record?.status !== 'published' && (
                <Button
                  type='button'
                  disabled={pending || !form.formState.isValid}
                  onClick={() =>
                    void form.handleSubmit((draft) =>
                      mutation.mutate({ draft, publish: true })
                    )()
                  }
                >
                  {pending ? '处理中…' : '保存并发布'}
                </Button>
              )}
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
