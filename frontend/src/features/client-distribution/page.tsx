import { useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { ClientDownloadsSettingsPage } from '@/features/platform/client-downloads-page'

const base = '/platform/client-distribution'
const queryKey = ['platform', 'client-distribution'] as const
type Release = Schema['DistributionView']
type Storage = Schema['StorageView']
type Artifact = Schema['ArtifactView']
type Target = Artifact['target']
const targets: Target[] = ['win-x64', 'mac-arm64', 'mac-x64']
const names: Record<Target, string> = {
  'win-x64': 'Windows x64',
  'mac-arm64': 'Mac Apple 芯片',
  'mac-x64': 'Mac Intel',
}
const statuses: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  withdrawn: '已下架',
  pending: '等待上传',
  verifying: '校验中',
  ready: '已校验',
  failed: '处理失败',
}
const roles = { installer: '安装包', payload: '更新包', blockmap: '差分索引' }

function TextField({
  label,
  error,
  ...props
}: ComponentProps<typeof Input> & { label: string; error?: string }) {
  return (
    <Field data-invalid={!!error}>
      <FieldLabel htmlFor={props.id}>{label}</FieldLabel>
      <Input {...props} aria-invalid={!!error} />
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

function Choice({
  label,
  id,
  value,
  onChange,
  choices,
}: {
  label: string
  id: string
  value: string
  onChange: (value: string) => void
  choices: [string, string][]
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {choices.map(([v, n]) => (
            <SelectItem key={v} value={v}>
              {n}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  )
}

function Editor({
  title,
  description,
  busy,
  close,
  children,
}: {
  title: string
  description: string
  busy: boolean
  close: () => void
  children: ReactNode
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <DialogContent
        className='max-h-[90dvh] overflow-y-auto sm:max-w-2xl'
        onInteractOutside={(e) => {
          if (busy) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}

export function ClientDistributionPage() {
  const [tab, setTab] = useState('updates')
  return (
    <Tabs value={tab} onValueChange={setTab} className='gap-0'>
      <TabsList className='mx-6 mt-5 w-fit'>
        <TabsTrigger value='updates'>更新发布</TabsTrigger>
        <TabsTrigger value='downloads'>下载目录</TabsTrigger>
      </TabsList>
      <TabsContent value='updates'>
        <DistributionSettings />
      </TabsContent>
      <TabsContent value='downloads'>
        <ClientDownloadsSettingsPage />
      </TabsContent>
    </Tabs>
  )
}

function DistributionSettings() {
  const { data: session } = useSession()
  const cache = useQueryClient()
  const [editing, setEditing] = useState<Release | 'new' | null>(null)
  const [storageEditor, setStorageEditor] = useState<Storage | 'new' | null>(
    null
  )
  const [uploading, setUploading] = useState<{
    releaseId: string
    artifact?: Artifact
  } | null>(null)
  const [publishing, setPublishing] = useState<Release | null>(null)
  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const [releases, storage, heads] = await Promise.all([
        api<{ items: Release[] }>(base + '/releases'),
        api<{ items: Storage[] }>(base + '/storage'),
        api<{ items: Schema['HeadView'][] }>(base + '/heads'),
      ])
      return {
        releases: releases.items,
        storage: storage.items,
        heads: heads.items,
      }
    },
    retry: false,
    refetchInterval: (q) =>
      q.state.data?.releases.some((r) =>
        r.artifacts.some((a) => a.status === 'verifying')
      )
        ? 5000
        : false,
  })
  const refresh = async () => {
    await cache.invalidateQueries({ queryKey })
    await cache.invalidateQueries({
      queryKey: ['platform', 'client-downloads'],
    })
    await cache.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  }
  const action = useMutation({
    mutationFn: ({
      path,
      body,
      method = 'POST',
    }: {
      path: string
      body?: unknown
      method?: string
    }) => api<Schema['Message']>(base + path, method, body, session?.csrf),
    onSuccess: async (result) => {
      toast.success(result.message || '操作已完成')
      await refresh()
    },
    onError: refresh,
  })
  return (
    <PageShell
      title='客户端更新发布'
      action={
        <>
          <Button variant='outline' onClick={() => void refresh()}>
            <RefreshCw />
            刷新
          </Button>
          <Button
            disabled={!query.data || query.isError}
            onClick={() => setEditing('new')}
          >
            <Plus />
            新建更新版本
          </Button>
        </>
      }
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <>
          <p className='mb-6 max-w-3xl text-sm text-muted-foreground'>
            配置存储后上传构建文件，或使用已有下载地址。文件校验通过后，可将版本发布到正式或预览更新通道。
          </p>
          {action.isError && <RequestError error={action.error} />}
          <Tabs defaultValue='releases'>
            <TabsList>
              <TabsTrigger value='releases'>版本与通道</TabsTrigger>
              <TabsTrigger value='storage'>对象存储</TabsTrigger>
            </TabsList>
            <TabsContent value='releases' className='space-y-5'>
              <Card>
                <CardHeader>
                  <CardTitle>当前更新通道</CardTitle>
                </CardHeader>
                <CardContent className='flex flex-wrap gap-2'>
                  {query.data.heads.length ? (
                    query.data.heads.map((h) => (
                      <Badge key={h.channel + h.target} variant='outline'>
                        {h.channel === 'latest' ? '正式' : '预览'} ·{' '}
                        {names[h.target]} ·{' '}
                        {h.release_id
                          ? query.data.releases.find(
                              (r) => r.id === h.release_id
                            )?.version || '已发布版本'
                          : '暂停推送'}
                      </Badge>
                    ))
                  ) : (
                    <p className='text-sm text-muted-foreground'>
                      尚未发布更新。发布后，使用本平台更新源构建的客户端会显示更新提示。
                    </p>
                  )}
                </CardContent>
              </Card>
              {!query.data.releases.length && (
                <p className='py-10 text-center text-muted-foreground'>
                  新建一个版本，开始准备客户端更新。
                </p>
              )}
              {query.data.releases.map((row) => (
                <Card key={row.id}>
                  <CardHeader className='flex-row flex-wrap items-center justify-between gap-3'>
                    <div className='flex items-center gap-3'>
                      <CardTitle>v{row.version}</CardTitle>
                      <Badge variant='secondary'>{statuses[row.status]}</Badge>
                      <span className='text-sm text-muted-foreground'>
                        {row.channel === 'latest' ? '正式' : '预览'}
                      </span>
                    </div>
                    <div className='flex flex-wrap gap-2'>
                      {row.status === 'draft' && (
                        <>
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => setEditing(row)}
                          >
                            编辑资料
                          </Button>
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => setUploading({ releaseId: row.id })}
                          >
                            <Upload />
                            添加文件
                          </Button>
                        </>
                      )}
                      {row.status !== 'withdrawn' && (
                        <Button size='sm' onClick={() => setPublishing(row)}>
                          {row.status === 'published'
                            ? '发布与下架'
                            : '检查并发布'}
                        </Button>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className='space-y-3'>
                    <p className='text-sm whitespace-pre-wrap text-muted-foreground'>
                      {row.notes || '暂无更新说明'}
                    </p>
                    {row.artifacts.map((a) => (
                      <div
                        key={a.id}
                        className='flex flex-wrap items-center justify-between gap-2 rounded-md border p-3'
                      >
                        <div className='min-w-0 space-y-1'>
                          <p className='text-sm font-medium break-all'>
                            {a.filename}
                          </p>
                          <p className='text-xs text-muted-foreground'>
                            {names[a.target]} · {roles[a.role]} ·{' '}
                            {a.size_bytes
                              ? (a.size_bytes / 1024 / 1024).toFixed(1) + ' MB'
                              : '大小待校验'}
                          </p>
                          {a.error && (
                            <p
                              role='alert'
                              className='text-sm text-destructive'
                            >
                              {a.error}
                            </p>
                          )}
                        </div>
                        <div className='flex flex-wrap items-center gap-2'>
                          <Badge
                            variant={
                              a.status === 'failed'
                                ? 'destructive'
                                : 'secondary'
                            }
                          >
                            {statuses[a.status] || a.status}
                          </Badge>
                          {row.status === 'draft' && a.status === 'pending' && (
                            <Button
                              size='sm'
                              variant='outline'
                              onClick={() =>
                                setUploading({ releaseId: row.id, artifact: a })
                              }
                            >
                              恢复上传
                            </Button>
                          )}
                          {row.status === 'draft' && a.status === 'failed' && (
                            <Button
                              size='sm'
                              variant='outline'
                              disabled={action.isPending}
                              onClick={() =>
                                action.mutate({
                                  path: '/artifacts/' + a.id + '/verify',
                                })
                              }
                            >
                              重新校验
                            </Button>
                          )}
                          {row.status === 'draft' &&
                            !['pending', 'verifying'].includes(a.status) && (
                              <Button
                                size='sm'
                                variant='ghost'
                                disabled={action.isPending}
                                onClick={() =>
                                  action.mutate({
                                    path: '/artifacts/' + a.id,
                                    method: 'DELETE',
                                    body: { expected_revision: row.revision },
                                  })
                                }
                              >
                                移除
                              </Button>
                            )}
                        </div>
                      </div>
                    ))}
                    {!row.artifacts.length && (
                      <p className='text-sm text-muted-foreground'>
                        还没有添加构建文件。
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </TabsContent>
            <TabsContent value='storage' className='space-y-4'>
              <Button onClick={() => setStorageEditor('new')}>
                <Plus />
                添加存储
              </Button>
              {query.data.storage.map((s) => (
                <Card key={s.id}>
                  <CardHeader>
                    <CardTitle>
                      {s.name} {s.is_default && <Badge>默认</Badge>}{' '}
                      {!s.enabled && <Badge variant='secondary'>已停用</Badge>}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className='space-y-3'>
                    <p className='text-sm break-all text-muted-foreground'>
                      {s.bucket} · {s.public_url}
                    </p>
                    <div className='flex gap-2'>
                      <Button
                        variant='outline'
                        onClick={() => setStorageEditor(s)}
                      >
                        编辑
                      </Button>
                      <Button
                        variant='outline'
                        disabled={action.isPending || !s.enabled}
                        onClick={() =>
                          action.mutate({ path: '/storage/' + s.id + '/test' })
                        }
                      >
                        测试连接
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
              <p className='text-sm text-muted-foreground'>
                支持 S3 兼容存储。公共下载地址需要支持 HTTPS 和
                Range；存储密钥加密保存在服务端。
              </p>
            </TabsContent>
          </Tabs>
          {editing && (
            <ReleaseEditor
              saved={editing === 'new' ? null : editing}
              close={() => setEditing(null)}
              changed={refresh}
              csrf={session?.csrf}
            />
          )}
          {storageEditor && (
            <StorageEditor
              saved={storageEditor === 'new' ? null : storageEditor}
              close={() => setStorageEditor(null)}
              changed={refresh}
              csrf={session?.csrf}
            />
          )}
          {uploading && (
            <ArtifactEditor
              releaseId={uploading.releaseId}
              artifact={uploading.artifact}
              storage={query.data.storage.filter((s) => s.enabled)}
              close={() => setUploading(null)}
              changed={refresh}
              csrf={session?.csrf}
            />
          )}
          {publishing && (
            <PublishEditor
              row={
                query.data.releases.find((r) => r.id === publishing.id) ||
                publishing
              }
              close={() => setPublishing(null)}
              changed={refresh}
              csrf={session?.csrf}
            />
          )}
        </>
      )}
    </PageShell>
  )
}

type EditorProps<T> = {
  saved: T | null
  csrf?: string
  close: () => void
  changed: () => Promise<void>
}
const storageSchema = z.object({
  name: z.string().trim().min(1, '请填写名称'),
  endpoint: z.url(),
  region: z.string().min(1),
  bucket: z.string().min(3),
  prefix: z.string().min(1),
  public_url: z.url(),
  access_key: z.string(),
  secret_key: z.string(),
  path_style: z.boolean(),
  enabled: z.boolean(),
  is_default: z.boolean(),
})
function StorageEditor({ saved, csrf, close, changed }: EditorProps<Storage>) {
  const [ident] = useState(saved?.id || crypto.randomUUID())
  const form = useForm({
    resolver: zodResolver(storageSchema),
    defaultValues: {
      name: saved?.name || '',
      endpoint: saved?.endpoint || '',
      region: saved?.region || 'us-east-1',
      bucket: saved?.bucket || '',
      prefix: saved?.prefix || 'clients',
      public_url: saved?.public_url || '',
      access_key: '',
      secret_key: '',
      path_style: saved?.path_style || false,
      enabled: saved?.enabled ?? true,
      is_default: saved?.is_default || false,
    },
  })
  const options = useWatch({ control: form.control })
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof storageSchema>) =>
      api(
        base + '/storage/' + ident,
        'PUT',
        {
          ...values,
          expected_revision: saved?.revision || 0,
          access_key: values.access_key || null,
          secret_key: values.secret_key || null,
        },
        csrf
      ),
    onSuccess: async () => {
      await changed()
      close()
    },
  })
  return (
    <Editor
      title={saved ? '编辑对象存储' : '添加对象存储'}
      description='公共下载地址填写桶或 CDN 的文件根地址，文件前缀会自动追加。'
      busy={mutation.isPending}
      close={close}
    >
      <form
        onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
        className='space-y-5'
      >
        <FieldGroup>
          {(
            [
              ['name', '名称'],
              ['endpoint', 'S3 服务地址'],
              ['region', '区域'],
              ['bucket', 'Bucket'],
              ['prefix', '文件前缀'],
              ['public_url', '公共下载根地址'],
              ['access_key', saved ? '访问密钥（留空保留）' : '访问密钥'],
              ['secret_key', saved ? '秘密密钥（留空保留）' : '秘密密钥'],
            ] as const
          ).map(([key, label]) => (
            <TextField
              key={key}
              id={key}
              label={label}
              {...form.register(key)}
              error={form.formState.errors[key]?.message}
              type={key.includes('key') ? 'password' : 'text'}
              autoComplete='off'
            />
          ))}
          {(
            [
              ['path_style', '使用路径形式访问 Bucket'],
              ['enabled', '启用存储'],
              ['is_default', '设为新上传的默认存储'],
            ] as const
          ).map(([key, label]) => (
            <Field key={key} orientation='horizontal'>
              <Checkbox
                id={key}
                checked={options[key]}
                onCheckedChange={(value) => form.setValue(key, value === true)}
              />
              <FieldLabel htmlFor={key}>{label}</FieldLabel>
            </Field>
          ))}
        </FieldGroup>
        {mutation.isError && <RequestError error={mutation.error} />}
        <Button disabled={mutation.isPending} type='submit'>
          {mutation.isPending ? '保存中…' : '保存存储'}
        </Button>
      </form>
    </Editor>
  )
}

const releaseSchema = z.object({
  version: z.string().min(1, '请填写版本号'),
  channel: z.enum(['latest', 'nightly']),
  notes: z.string().max(12000),
  win: z.string(),
  arm: z.string(),
  intel: z.string(),
})
function ReleaseEditor({ saved, csrf, close, changed }: EditorProps<Release>) {
  const [ident] = useState(saved?.id || crypto.randomUUID())
  const form = useForm({
    resolver: zodResolver(releaseSchema),
    defaultValues: {
      version: saved?.version || '',
      channel: saved?.channel || 'latest',
      notes: saved?.notes || '',
      win: saved?.minimum_os['win-x64'] || 'Windows 10 及以上',
      arm: saved?.minimum_os['mac-arm64'] || 'macOS 13 及以上',
      intel: saved?.minimum_os['mac-x64'] || 'macOS 13 及以上',
    },
  })
  const channel = useWatch({ control: form.control, name: 'channel' })
  const mutation = useMutation({
    mutationFn: (v: z.infer<typeof releaseSchema>) =>
      api(
        base + '/releases/' + ident,
        'PUT',
        {
          expected_revision: saved?.revision || 0,
          version: v.version,
          channel: v.channel,
          notes: v.notes,
          minimum_os: {
            'win-x64': v.win,
            'mac-arm64': v.arm,
            'mac-x64': v.intel,
          },
        },
        csrf
      ),
    onSuccess: async () => {
      await changed()
      close()
    },
  })
  return (
    <Editor
      title={saved ? '编辑版本资料' : '新建更新版本'}
      description='正式通道使用稳定版本号；预发布版本请使用预览通道。最低系统要求应与实际构建一致。'
      busy={mutation.isPending}
      close={close}
    >
      <form
        onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
        className='space-y-5'
      >
        <FieldGroup>
          <TextField
            id='version'
            label='版本号'
            placeholder='例如 1.0.0'
            disabled={!!saved}
            {...form.register('version')}
            error={form.formState.errors.version?.message}
          />
          {!saved && (
            <Choice
              id='channel'
              label='更新通道'
              value={channel}
              onChange={(v) =>
                form.setValue('channel', v as 'latest' | 'nightly')
              }
              choices={[
                ['latest', '正式'],
                ['nightly', '预览'],
              ]}
            />
          )}
          <Field>
            <FieldLabel htmlFor='notes'>更新说明</FieldLabel>
            <Textarea id='notes' rows={4} {...form.register('notes')} />
          </Field>
          {(
            [
              ['win', 'Windows x64 最低要求'],
              ['arm', 'Mac Apple 芯片最低要求'],
              ['intel', 'Mac Intel 最低要求'],
            ] as const
          ).map(([key, label]) => (
            <TextField
              key={key}
              id={key}
              label={label}
              {...form.register(key)}
            />
          ))}
        </FieldGroup>
        {mutation.isError && <RequestError error={mutation.error} />}
        <Button disabled={mutation.isPending} type='submit'>
          {mutation.isPending ? '保存中…' : '保存草稿'}
        </Button>
      </form>
    </Editor>
  )
}

function ArtifactEditor({
  releaseId,
  artifact,
  storage,
  csrf,
  close,
  changed,
}: {
  releaseId: string
  artifact?: Artifact
  storage: Storage[]
  csrf?: string
  close: () => void
  changed: () => Promise<void>
}) {
  const [target, setTarget] = useState<Target>(artifact?.target || 'win-x64')
  const [role, setRole] = useState<Artifact['role']>(
    artifact?.role || 'payload'
  )
  const [mode, setMode] = useState('file')
  const [storageId, setStorageId] = useState(
    artifact?.storage_id ||
      storage.find((s) => s.is_default)?.id ||
      storage[0]?.id ||
      ''
  )
  const [url, setUrl] = useState('')
  const [filename, setFilename] = useState('')
  const [sha512, setSha512] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [ident] = useState(artifact?.id || crypto.randomUUID())
  const [progress, setProgress] = useState(0)
  const [started, setStarted] = useState(!!artifact)
  const pause = useRef(false)
  const mutation = useMutation({
    mutationFn: async () => {
      pause.current = false
      if (mode === 'file' && !file) throw new Error('请选择构建文件')
      if (
        artifact &&
        file &&
        (file.name !== artifact.filename || file.size !== artifact.size_bytes)
      )
        throw new Error('请选择名称和大小均与任务一致的原文件')
      if (mode !== 'url' && !storageId)
        throw new Error('请先添加并启用对象存储')
      if (mode !== 'file' && !url) throw new Error('请填写 HTTPS 下载地址')
      if (!started) {
        const row = await api<Release>(base + '/releases/' + releaseId)
        await api<Artifact>(
          base + '/releases/' + releaseId + '/artifacts/' + ident,
          'PUT',
          {
            expected_revision: row.revision,
            target,
            role,
            filename: mode === 'file' ? file!.name : filename,
            size_bytes: mode === 'file' ? file!.size : null,
            sha512: sha512 || null,
            url: mode === 'file' ? null : url,
            mirror: mode === 'mirror',
            storage_id: mode === 'url' ? null : storageId,
          },
          csrf
        )
        setStarted(true)
      }
      if (mode === 'file' && file) {
        const session = await api<Schema['UploadView']>(
          base + '/uploads/' + ident + '/start',
          'POST',
          undefined,
          csrf
        )
        if (session.status !== 'completed') {
          if (session.status === 'completing') {
            await api(
              base + '/uploads/' + ident + '/complete',
              'POST',
              undefined,
              csrf
            )
            return true
          }
          for (let n = 1; n <= session.part_count; n++) {
            if (pause.current) return false
            if (artifact || !session.parts[String(n)]) {
              const blob = file.slice(
                (n - 1) * session.part_size,
                n * session.part_size
              )
              const ack = await api<Schema['PartAck']>(
                base + '/uploads/' + ident + '/parts/' + n,
                'PUT',
                blob,
                csrf
              )
              await api(base + '/uploads/' + ident + '/ack', 'POST', ack, csrf)
            }
            setProgress(Math.round((n / session.part_count) * 100))
          }
          await api(
            base + '/uploads/' + ident + '/complete',
            'POST',
            undefined,
            csrf
          )
        }
      }
      return true
    },
    onSuccess: async (complete) => {
      await changed()
      if (complete) {
        toast.success('文件已提交校验')
        close()
      }
    },
    onError: changed,
  })
  const cancel = useMutation({
    mutationFn: async () => {
      await api(base + '/uploads/' + ident + '/abort', 'POST', undefined, csrf)
      const row = await api<Release>(base + '/releases/' + releaseId)
      await api(
        base + '/artifacts/' + ident,
        'DELETE',
        { expected_revision: row.revision },
        csrf
      )
    },
    onSuccess: async () => {
      await changed()
      close()
    },
  })
  return (
    <Editor
      title='添加构建文件'
      description='Windows 添加 EXE 和配套 blockmap；Mac 添加 DMG、ZIP 和 ZIP.blockmap。安装包应使用本平台更新源构建。'
      busy={mutation.isPending || cancel.isPending}
      close={close}
    >
      <form
        className='space-y-5'
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <fieldset disabled={started || mutation.isPending}>
          <FieldGroup>
            <Choice
              id='target'
              label='系统与架构'
              value={target}
              onChange={(v) => {
                setTarget(v as Target)
                if (v === 'win-x64' && role === 'installer') setRole('payload')
              }}
              choices={targets.map((t) => [t, names[t]])}
            />
            <Choice
              id='role'
              label='文件用途'
              value={role}
              onChange={(v) => setRole(v as Artifact['role'])}
              choices={Object.entries(roles).filter(
                ([v]) => target !== 'win-x64' || v !== 'installer'
              )}
            />
            <Choice
              id='source'
              label='文件来源'
              value={mode}
              onChange={setMode}
              choices={[
                ['file', '上传本地文件'],
                ['url', '引用已有地址'],
                ['mirror', '从地址转存'],
              ]}
            />
            {mode !== 'url' && (
              <Choice
                id='storage'
                label='存储位置'
                value={storageId}
                onChange={setStorageId}
                choices={storage.map((s) => [s.id, s.name])}
              />
            )}
            {mode === 'file' && !artifact ? (
              <TextField
                id='file'
                label='选择文件'
                type='file'
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            ) : mode !== 'file' ? (
              <>
                <TextField
                  id='url'
                  label='HTTPS 下载地址'
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  required
                />
                <TextField
                  id='filename'
                  label='文件名（包括扩展名）'
                  value={filename}
                  onChange={(e) => setFilename(e.target.value)}
                  required
                />
              </>
            ) : null}
            <TextField
              id='sha512'
              label='预期 SHA-512（base64，可选）'
              value={sha512}
              onChange={(e) => setSha512(e.target.value)}
            />
          </FieldGroup>
        </fieldset>
        {artifact && (
          <FieldGroup>
            <TextField
              id='resume-file'
              label={'重新选择 ' + artifact.filename}
              type='file'
              disabled={mutation.isPending}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <p className='text-sm text-muted-foreground'>
              重新选择文件后会重传各分片，避免混合不同文件。需要跨会话断点续传时可使用
              CLI。
            </p>
          </FieldGroup>
        )}
        {started && mode === 'file' && (
          <div className='space-y-2' aria-live='polite'>
            <Progress value={progress} aria-label='文件上传进度' />
            <p className='text-sm text-muted-foreground'>
              已上传 {progress}% ·
              关闭页面前请完成或取消上传；构建批量上传可使用 CLI 续传。
            </p>
          </div>
        )}
        {mutation.isError && <RequestError error={mutation.error} />}
        {cancel.isError && <RequestError error={cancel.error} />}
        <div className='flex gap-2'>
          <Button
            type='submit'
            disabled={mutation.isPending || cancel.isPending}
          >
            {mutation.isPending ? '处理中…' : started ? '继续上传' : '提交文件'}
          </Button>
          {mutation.isPending && mode === 'file' && (
            <Button
              type='button'
              variant='outline'
              onClick={() => {
                pause.current = true
              }}
            >
              当前分片完成后暂停
            </Button>
          )}
          {started && mode === 'file' && !mutation.isPending && (
            <Button
              type='button'
              variant='outline'
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              取消上传
            </Button>
          )}
        </div>
      </form>
    </Editor>
  )
}

function PublishEditor({
  row,
  csrf,
  close,
  changed,
}: {
  row: Release
  csrf?: string
  close: () => void
  changed: () => Promise<void>
}) {
  const [selected, setSelected] = useState<Target[]>(
    Array.from(new Set(row.artifacts.map((a) => a.target)))
  )
  const [plan, setPlan] = useState<Schema['PlanView'] | null>(null)
  const [withdraw, setWithdraw] = useState(false)
  const mutation = useMutation({
    mutationFn: async (action: 'plan' | 'publish' | 'withdraw') => {
      if (action === 'plan') {
        const result = await api<Schema['PlanView']>(
          base + '/releases/' + row.id + '/plan',
          'POST',
          { expected_revision: row.revision, targets: selected },
          csrf
        )
        setPlan(result)
        return false
      }
      await api(
        base + '/releases/' + row.id + '/' + action,
        'POST',
        action === 'publish'
          ? { plan_id: plan!.id }
          : { expected_revision: row.revision },
        csrf
      )
      return true
    },
    onSuccess: async (complete) => {
      if (complete) {
        await changed()
        close()
      }
    },
    onError: async () => {
      await changed()
    },
  })
  return (
    <Editor
      title={'发布 v' + row.version}
      description='检查文件后生成有效期 15 分钟的发布计划，确认发布才会切换所选通道。'
      busy={mutation.isPending}
      close={close}
    >
      <FieldGroup>
        {targets.map((t) => (
          <Field key={t} orientation='horizontal'>
            <Checkbox
              id={'publish-' + t}
              disabled={!!plan || mutation.isPending}
              checked={selected.includes(t)}
              onCheckedChange={(v) =>
                setSelected(
                  v === true
                    ? [...selected, t]
                    : selected.filter((x) => x !== t)
                )
              }
            />
            <FieldLabel htmlFor={'publish-' + t}>{names[t]}</FieldLabel>
          </Field>
        ))}
      </FieldGroup>
      {plan && (
        <p className='rounded-md border p-3 text-sm'>
          检查通过。确认后，{row.channel === 'latest' ? '正式' : '预览'}通道的{' '}
          {selected.map((t) => names[t]).join('、')} 将推送 v{row.version}
          。下载页也会同步更新。
        </p>
      )}
      {mutation.isError && <RequestError error={mutation.error} />}
      <div className='flex flex-wrap gap-2'>
        {plan ? (
          <>
            <Button
              disabled={mutation.isPending}
              onClick={() => mutation.mutate('publish')}
            >
              确认发布
            </Button>
            <Button
              variant='outline'
              disabled={mutation.isPending}
              onClick={() => setPlan(null)}
            >
              重新检查
            </Button>
          </>
        ) : (
          <Button
            disabled={!selected.length || mutation.isPending}
            onClick={() => mutation.mutate('plan')}
          >
            检查发布条件
          </Button>
        )}
        {row.status === 'published' && (
          <Button
            variant='outline'
            disabled={mutation.isPending}
            onClick={() => setWithdraw(true)}
          >
            下架此版本
          </Button>
        )}
      </div>
      {withdraw && (
        <div className='space-y-3 rounded-md border p-4'>
          <p className='text-sm'>
            下架会移除下载入口并暂停仍指向此版本的更新通道。已经下载的更新无法撤回，也不会自动降级。
          </p>
          <Button
            variant='destructive'
            disabled={mutation.isPending}
            onClick={() => mutation.mutate('withdraw')}
          >
            确认下架
          </Button>
        </div>
      )}
    </Editor>
  )
}
