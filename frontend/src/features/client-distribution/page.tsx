import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Progress } from '@/components/ui/progress'
import { Textarea } from '@/components/ui/textarea'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { TextField, Choice, Editor } from '@/components/settings-editor'
import { useSession } from '@/features/auth/session'

const base = '/platform/client-distribution'
const queryKey = ['platform', 'client-distribution'] as const
type Release = Schema['DistributionView']
type Storage = Schema['StorageView']
type Artifact = Schema['ArtifactView']
type Target = Artifact['target']
const targets: Target[] = ['win-x64', 'win-arm64', 'mac-arm64', 'mac-x64']
const names: Record<Target, string> = {
  'win-x64': 'Windows x64',
  'win-arm64': 'Windows ARM64',
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

export function ClientDistributionPage() {
  return <DistributionSettings />
}

function DistributionSettings() {
  const { data: session } = useSession()
  const cache = useQueryClient()
  const [editing, setEditing] = useState<Release | 'new' | null>(null)
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
        api<{ items: Storage[] }>('/platform/object-storage'),
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
      title='客户端版本'
      action={
        <>
          <Button
            disabled={!query.data || query.isError}
            onClick={() => setEditing('new')}
          >
            <Plus />
            新建版本
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
          {action.isError && <RequestError error={action.error} />}
          <div className='space-y-5'>
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
                        ? query.data.releases.find((r) => r.id === h.release_id)
                            ?.version || '已发布版本'
                        : '暂停推送'}
                    </Badge>
                  ))
                ) : (
                  <p className='text-sm text-muted-foreground'>尚未发布更新</p>
                )}
              </CardContent>
            </Card>
            {!query.data.releases.length && (
              <p className='py-10 text-center text-muted-foreground'>
                暂无客户端版本
              </p>
            )}
            {query.data.releases.map((row) => (
              <Card key={row.id}>
                <CardHeader className='flex-row flex-wrap items-center justify-between gap-3'>
                  <div className='flex items-center gap-3'>
                    <CardTitle>v{row.version}</CardTitle>
                    <Badge variant='secondary'>{statuses[row.status]}</Badge>
                    {row.legacy && <Badge variant='outline'>历史版本</Badge>}
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
                          disabled={row.legacy}
                          onClick={() => setUploading({ releaseId: row.id })}
                        >
                          <Upload />
                          添加文件
                        </Button>
                      </>
                    )}
                    {row.status !== 'withdrawn' &&
                      (!row.legacy || row.status === 'published') &&
                      (row.legacy ? (
                        <Button
                          size='sm'
                          variant='outline'
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate({
                              path: '/releases/' + row.id + '/withdraw',
                              body: { expected_revision: row.revision },
                            })
                          }
                        >
                          下架
                        </Button>
                      ) : (
                        <Button size='sm' onClick={() => setPublishing(row)}>
                          {row.status === 'published'
                            ? '发布与下架'
                            : '检查并发布'}
                        </Button>
                      ))}
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
                          <p role='alert' className='text-sm text-destructive'>
                            {a.error}
                          </p>
                        )}
                      </div>
                      <div className='flex flex-wrap items-center gap-2'>
                        <Badge
                          variant={
                            a.status === 'failed' ? 'destructive' : 'secondary'
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
                  {row.legacy_assets?.map((a) => (
                    <a
                      className='block text-sm underline'
                      key={a.platform + a.architecture}
                      href={a.url}
                    >
                      {a.filename || `${a.platform} ${a.architecture}`}
                    </a>
                  ))}
                  {!row.artifacts.length && !row.legacy && (
                    <p className='text-sm text-muted-foreground'>
                      还没有添加构建文件。
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
          {editing && (
            <ReleaseEditor
              saved={editing === 'new' ? null : editing}
              close={() => setEditing(null)}
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
const releaseSchema = z.object({
  version: z.string().min(1, '请填写版本号'),
  channel: z.enum(['latest', 'nightly']),
  notes: z.string().max(12000),
  win: z.string(),
  winArm: z.string(),
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
      winArm: saved?.minimum_os['win-arm64'] || 'Windows 11 ARM64',
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
            'win-arm64': v.winArm,
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
      title={saved ? '编辑版本资料' : '新建版本'}
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
            disabled={!!saved && !saved.legacy}
            {...form.register('version')}
            error={form.formState.errors.version?.message}
          />
          {(!saved || saved.legacy) && (
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
              ['winArm', 'Windows ARM64 最低要求'],
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
  const [files, setFiles] = useState<File[]>([])
  const identifiers = useRef(new Map<string, string>())
  const activeId = useRef(artifact?.id || '')
  const storageId =
    artifact?.storage_id || storage.find((s) => s.enabled && s.is_default)?.id
  const [progress, setProgress] = useState(0)
  const [started, setStarted] = useState(!!artifact)
  const pause = useRef(false)
  const mutation = useMutation({
    mutationFn: async () => {
      pause.current = false
      if (!files.length) throw new Error('请选择构建文件')
      const seen = new Set<string>()
      for (const file of files) {
        const role = file.name.endsWith('.blockmap')
          ? 'blockmap'
          : file.name.endsWith('.dmg')
            ? 'installer'
            : 'payload'
        const extension = target.startsWith('win-')
          ? '.exe'
          : role === 'installer'
            ? '.dmg'
            : '.zip'
        if (
          !file.name.endsWith(
            extension + (role === 'blockmap' ? '.blockmap' : '')
          ) ||
          seen.has(role)
        )
          throw new Error('文件类型与架构不符，或重复选择了同类文件')
        seen.add(role)
      }
      for (let index = 0; index < files.length; index++) {
        const file = files[index]
        const role =
          artifact?.role ||
          (file.name.endsWith('.blockmap')
            ? 'blockmap'
            : file.name.endsWith('.dmg')
              ? 'installer'
              : 'payload')
        let ident = artifact?.id || identifiers.current.get(file.name)
        if (!ident) {
          ident = crypto.randomUUID()
          identifiers.current.set(file.name, ident)
        }
        activeId.current = ident
        if (
          artifact &&
          file &&
          (file.name !== artifact.filename || file.size !== artifact.size_bytes)
        )
          throw new Error('请选择名称和大小均与任务一致的原文件')
        if (!storageId) throw new Error('请先添加并启用对象存储')
        if (!artifact) {
          const row = await api<Release>(base + '/releases/' + releaseId)
          await api<Artifact>(
            base + '/releases/' + releaseId + '/artifacts/' + ident,
            'PUT',
            {
              expected_revision: row.revision,
              target,
              role,
              filename: file!.name,
              size_bytes: file.size,
              sha512: null,
              url: null,
              mirror: false,
              storage_id: storageId,
            },
            csrf
          )
          setStarted(true)
        }
        {
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
              continue
            }
            for (let n = 1; n <= session.part_count; n++) {
              if (pause.current) return false
              {
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
                await api(
                  base + '/uploads/' + ident + '/ack',
                  'POST',
                  ack,
                  csrf
                )
              }
              setProgress(
                Math.round(
                  ((index + n / session.part_count) / files.length) * 100
                )
              )
            }
            await api(
              base + '/uploads/' + ident + '/complete',
              'POST',
              undefined,
              csrf
            )
          }
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
      await api(
        base + '/uploads/' + activeId.current + '/abort',
        'POST',
        undefined,
        csrf
      )
      const row = await api<Release>(base + '/releases/' + releaseId)
      await api(
        base + '/artifacts/' + activeId.current,
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
      busy={mutation.isPending || cancel.isPending}
      close={close}
    >
      {!storageId && (
        <p role='alert'>
          尚未设置默认对象存储。
          <a className='underline' href='/platform/settings/storage'>
            前往设置
          </a>
        </p>
      )}
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
              }}
              choices={targets.map((t) => [t, names[t]])}
            />
            {!artifact && (
              <TextField
                id='file'
                label='构建文件'
                type='file'
                accept={
                  target.startsWith('win-')
                    ? '.exe,.blockmap'
                    : '.dmg,.zip,.blockmap'
                }
                multiple={!artifact}
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
            )}
          </FieldGroup>
        </fieldset>
        {artifact && (
          <FieldGroup>
            <TextField
              id='resume-file'
              label={'重新选择 ' + artifact.filename}
              type='file'
              disabled={mutation.isPending}
              multiple={!artifact}
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
            <p className='text-sm text-muted-foreground'>{artifact.filename}</p>
          </FieldGroup>
        )}
        {started && (
          <div className='space-y-2' aria-live='polite'>
            <Progress value={progress} aria-label='文件上传进度' />
            <p className='text-sm text-muted-foreground'>已上传 {progress}%</p>
          </div>
        )}
        {mutation.isError && <RequestError error={mutation.error} />}
        {cancel.isError && <RequestError error={cancel.error} />}
        <div className='flex gap-2'>
          <Button
            type='submit'
            disabled={!storageId || mutation.isPending || cancel.isPending}
          >
            {mutation.isPending ? '处理中…' : started ? '继续上传' : '提交文件'}
          </Button>
          {mutation.isPending && (
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
          {started && !mutation.isPending && (
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
