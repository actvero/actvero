import { useState } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { AvatarEditor } from '@/components/avatar-editor'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageShell } from '@/components/layout/page-shell'
import { MemberPicker } from '@/components/member-picker'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { SearchSelect } from '@/components/search-select'
import { ExpertActions } from './actions'
import { ExpertCategoryPicker } from './category-picker'
import { DependencyCard } from './dependency-card'
import { DependencyRecoveryNotice } from './dependency-command'
import { DependencyPicker } from './dependency-picker'
import {
  scopeLabels,
  statusLabels,
  useExperts,
  useCategories,
  type Expert,
  type Content,
} from './shared'
import { SkillReferenceUpdateDialog } from './skill-reference-update-dialog'
import { useDependencyCommand } from './use-dependency-command'

const splitTags = (s: string) =>
  s
    .split(/[,，\n]/)
    .map((v) => v.trim())
    .filter(Boolean)
const splitStarters = (s: string) =>
  s
    .split('\n')
    .map((v) => v.trim())
    .filter(Boolean)
const schema = z.object({
  name: z.string().trim().min(1, '请输入名称').max(80),
  description: z.string().trim().min(1, '请输入简介').max(500),
  avatar: z.string(),
  category: z.string().min(1, '请选择类别'),
  instructions: z.string().trim().max(64000),
  tags_text: z
    .string()
    .refine(
      (v) =>
        splitTags(v).length <= 8 && splitTags(v).every((t) => t.length <= 30),
      '最多 8 个标签，每个不超过 30 字'
    ),
  starters_text: z
    .string()
    .refine(
      (v) =>
        splitStarters(v).length <= 6 &&
        splitStarters(v).every((t) => t.length <= 1000),
      '最多 6 个开场问题，每个不超过 1000 字'
    ),
  skills: z.array(z.custom<Content['skills'][number]>()).max(32),
  connectors: z.array(z.custom<Content['connectors'][number]>()).max(32),
})
type Values = z.infer<typeof schema>
const empty: Values = {
  name: '',
  description: '',
  avatar: '',
  category: 'uncategorized',
  instructions: '',
  tags_text: '',
  starters_text: '',
  skills: [],
  connectors: [],
}
function defaults(expert?: Expert): Values {
  if (!expert) return empty
  return {
    ...expert.content,
    skills: expert.content.skills ?? [],
    connectors: expert.content.connectors ?? [],
    category: expert.category.id,
    tags_text: (expert.content.tags ?? []).join(', '),
    starters_text: (expert.content.conversation_starters ?? []).join('\n'),
  }
}
const dependencyLabels = {
  available: '版本有效',
  unavailable: '不可用',
  version_conflict: '依赖需要检查',
  unverified: '能力定义尚未核实',
}

function Checks({ check }: { check: Schema['ExpertCheck'] }) {
  const issues = check.dependencies.filter(
    (d) =>
      d.status !== 'available' || d.missing_members > 0 || d.update_available
  )
  return (
    <div className='flex flex-col gap-3'>
      {check.instruction_missing && (
        <Alert>
          <AlertTitle>填写工作指令后可以发布</AlertTitle>
        </Alert>
      )}
      {issues.map((d) => (
        <Alert key={d.kind + d.key}>
          <AlertTitle>
            {d.label} · {d.required ? '必需' : '可选'}
          </AlertTitle>
          <AlertDescription>
            {d.status !== 'available' && (
              <span>
                {d.kind === 'connectors' && d.status === 'version_conflict'
                  ? '能力定义、提示词内容或开放范围已变化，请确认连接器目录并检查依赖。'
                  : `${dependencyLabels[d.status]}。请重新选择有效能力。`}
              </span>
            )}
            {d.update_available && d.status === 'available' && (
              <span>
                有新版。当前锁定 v{d.locked_version}{' '}
                仍可使用，更新需要主动确认。
              </span>
            )}
            {d.missing_members > 0 && (
              <span>{d.missing_members} 位所选成员没有此能力的使用权限。</span>
            )}
          </AlertDescription>
        </Alert>
      ))}
    </div>
  )
}

function PublishDialog({
  expert,
  close,
  saved,
}: {
  expert: Expert
  close: () => void
  saved: (e: Expert) => void
}) {
  const { csrf } = useExperts()
  const [error, setError] = useState<unknown>()
  const form = useForm({
    resolver: zodResolver(
      z.object({
        version: z
          .string()
          .regex(/^\d+\.\d+\.\d+$/, '请填写如 1.0.0 的版本号')
          .max(30),
        release_notes: z.string().max(4000),
      })
    ),
    defaultValues: { version: '', release_notes: '' },
  })
  const busy = form.formState.isSubmitting
  return (
    <Dialog open onOpenChange={(v) => !v && !busy && close()}>
      <DialogContent className='max-h-[calc(100svh-2rem)] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>发布{expert.name}</DialogTitle>
          <DialogDescription>
            新召唤使用此版本，已有会话保留原版本。本次发布锁定所选工具及当时开放的提示词、资源和资源模板，
            定义变化后需检查依赖并发布新版；下架或撤权仍会阻止访问。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit(async (values) => {
              setError(undefined)
              try {
                saved(
                  await api<Expert>(
                    `/experts/${expert.id}/publish`,
                    'POST',
                    { ...values, revision: expert.revision },
                    csrf
                  )
                )
                toast.success('专家已发布')
                close()
              } catch (e) {
                setError(e)
              }
            })}
          >
            <FormField
              control={form.control}
              name='version'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>版本号</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder='例如 1.0.0'
                      disabled={busy}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='release_notes'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>更新说明</FormLabel>
                  <FormControl>
                    <Textarea {...field} disabled={busy} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Checks check={expert.check} />
            {error != null && <RequestError error={error} />}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                disabled={busy}
                onClick={close}
              >
                取消
              </Button>
              <Button disabled={busy || !expert.check.can_publish}>
                {busy ? '发布中…' : '确认发布'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

function Scope({
  expert,
  saved,
  disabled,
  onSavingChange,
}: {
  expert: Expert
  saved: (e: Expert) => void
  disabled: boolean
  onSavingChange: (saving: boolean) => void
}) {
  const { csrf } = useExperts()
  const [error, setError] = useState<unknown>()
  const form = useForm({
    resolver: zodResolver(
      z
        .object({
          audience: z.enum(['administrators', 'selected', 'organization']),
          member_ids: z.array(z.string()),
        })
        .refine((v) => v.audience !== 'selected' || v.member_ids.length > 0, {
          path: ['member_ids'],
          message: '请选择至少一名成员',
        })
    ),
    defaultValues: { audience: expert.audience, member_ids: expert.member_ids },
  })
  const audience = useWatch({ control: form.control, name: 'audience' })
  const busy = disabled || form.formState.isSubmitting
  return (
    <Form {...form}>
      <form
        className='flex max-w-3xl flex-col gap-5'
        onSubmit={form.handleSubmit(async (values) => {
          setError(undefined)
          onSavingChange(true)
          try {
            const result = await api<Expert>(
              `/experts/${expert.id}/scope`,
              'PUT',
              {
                ...values,
                member_ids:
                  values.audience === 'selected' ? values.member_ids : [],
                revision: expert.revision,
              },
              csrf
            )
            form.reset({
              audience: result.audience,
              member_ids: result.member_ids,
            })
            saved(result)
            toast.success('使用范围已保存')
          } catch (e) {
            setError(e)
          } finally {
            onSavingChange(false)
          }
        })}
      >
        <FormField
          control={form.control}
          name='audience'
          render={({ field }) => (
            <FormItem>
              <FormLabel>谁可以使用这位专家</FormLabel>
              <FormControl>
                <SearchSelect
                  value={field.value}
                  onValueChange={field.onChange}
                  disabled={busy}
                  items={Object.entries(scopeLabels).map(([value, label]) => ({
                    value,
                    label,
                  }))}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {audience === 'selected' && (
          <FormField
            control={form.control}
            name='member_ids'
            render={({ field }) => (
              <FormItem>
                <FormLabel>指定成员</FormLabel>
                <FormControl>
                  <MemberPicker
                    includeAdministrators
                    value={field.value}
                    onChange={field.onChange}
                    disabled={busy}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
        <p className='text-sm text-muted-foreground'>
          使用范围保存后立即生效。使用专家仍需具备所引用能力的权限。
        </p>
        {error != null && <RequestError error={error} />}
        <div>
          <Button disabled={busy}>保存范围</Button>
        </div>
        <Checks check={expert.check} />
      </form>
    </Form>
  )
}

function Editor({
  expert: initialExpert,
  saved: onSaved,
}: {
  expert?: Expert
  saved: (e: Expert) => void
}) {
  const { csrf } = useExperts()
  const navigate = useNavigate()
  // Keep the revision tied to the last response accepted by this editor.
  // Background query refreshes must not replace a pending local draft.
  const [expert, setExpert] = useState(initialExpert)
  const [tab, setTab] = useState('config')
  const [savingScope, setSavingScope] = useState(false)
  function saved(result: Expert) {
    setExpert(result)
    onSaved(result)
  }
  const categories = useCategories()
  const [error, setError] = useState<unknown>()
  const [picker, setPicker] = useState<'skills' | 'connectors'>()
  const [publish, setPublish] = useState(false)
  const [withdraw, setWithdraw] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [updates, setUpdates] = useState(false)
  const [reloading, setReloading] = useState(false)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: defaults(expert),
  })
  const values = useWatch({ control: form.control })
  const command = useDependencyCommand(
    expert?.id ?? '',
    'expert.refresh_skills',
    async (isLive) => {
      if (!expert) return
      const result = await api<Expert>(`/experts/${expert.id}`)
      if (!isLive()) return
      form.reset(defaults(result))
      saved(result)
      setUpdates(false)
      toast.success('已更新所选技能引用，请检查草稿后发布')
    }
  )
  const busy =
    form.formState.isSubmitting ||
    withdrawing ||
    savingScope ||
    reloading ||
    command.busy ||
    !!command.pending ||
    command.forbidden
  const dirty = form.formState.isDirty
  async function submit(v: Values) {
    setError(undefined)
    const { category, tags_text, starters_text, ...rest } = v
    try {
      const result = await api<Expert>(
        expert ? `/experts/${expert.id}` : '/experts',
        expert ? 'PUT' : 'POST',
        {
          category,
          content: {
            ...rest,
            tags: splitTags(tags_text),
            conversation_starters: splitStarters(starters_text),
          },
          ...(expert ? { revision: expert.revision } : {}),
        },
        csrf
      )
      form.reset(defaults(result))
      saved(result)
      toast.success('草稿已保存')
    } catch (e) {
      setError(e)
    }
  }
  if (command.forbidden)
    return (
      <PageShell title='专家'>
        <RequestError error={command.error} />
      </PageShell>
    )
  return (
    <PageShell
      title={expert ? expert.name : '创建专家'}
      titleAfter={
        expert && (
          <div className='flex flex-wrap gap-2'>
            <Badge variant='secondary'>{statusLabels[expert.status]}</Badge>
            {expert.current_release && (
              <Badge variant='outline'>v{expert.current_release.version}</Badge>
            )}
            {(dirty || expert.has_changes) && (
              <Badge variant='outline'>有未发布修改</Badge>
            )}
          </div>
        )
      }
      action={
        <div className='flex flex-wrap gap-2'>
          <Button variant='outline' asChild>
            <Link to='/experts'>
              <ArrowLeft />
              返回
            </Link>
          </Button>
          <Button variant='outline' form='expert-config' disabled={busy}>
            {busy ? '保存中…' : '保存草稿'}
          </Button>
          {expert && (
            <Button
              disabled={busy || dirty || !expert.check.can_publish}
              onClick={() => setPublish(true)}
            >
              发布
            </Button>
          )}
          {expert && (
            <ExpertActions
              expert={expert}
              disabled={busy}
              changed={saved}
              deleted={async () => {
                await navigate({ to: '/experts' })
              }}
            />
          )}
        </div>
      }
    >
      {error != null && <RequestError error={error} />}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value='config'>配置</TabsTrigger>
          <TabsTrigger value='scope' disabled={!expert}>
            使用范围
          </TabsTrigger>
          <TabsTrigger value='versions' disabled={!expert}>
            版本记录
          </TabsTrigger>
        </TabsList>
        <TabsContent
          value='config'
          forceMount
          hidden={tab !== 'config'}
          className='pt-4'
        >
          <div className='grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
            <Form {...form}>
              <form
                id='expert-config'
                className='flex min-w-0 flex-col gap-6'
                onSubmit={form.handleSubmit(submit)}
              >
                <div className='flex items-center gap-4'>
                  <AvatarEditor
                    value={values.avatar}
                    fallback={(values.name || '专家').slice(0, 1)}
                    disabled={busy}
                    onChange={async (file) => {
                      const image = file
                        ? await new Promise<string>((resolve, reject) => {
                            const reader = new FileReader()
                            reader.onload = () => resolve(String(reader.result))
                            reader.onerror = () =>
                              reject(new Error('读取图片失败'))
                            reader.readAsDataURL(file)
                          })
                        : ''
                      form.setValue('avatar', image, { shouldDirty: true })
                    }}
                  />
                  <FormField
                    control={form.control}
                    name='name'
                    render={({ field }) => (
                      <FormItem className='min-w-0 flex-1'>
                        <FormLabel>名称</FormLabel>
                        <FormControl>
                          <Input {...field} maxLength={80} disabled={busy} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <FormField
                  control={form.control}
                  name='description'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>简介</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          maxLength={500}
                          rows={3}
                          disabled={busy}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className='grid gap-4 sm:grid-cols-2'>
                  <FormField
                    control={form.control}
                    name='category'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>类别</FormLabel>
                        <FormControl>
                          <ExpertCategoryPicker
                            value={field.value}
                            onValueChange={field.onChange}
                            disabled={busy}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name='tags_text'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>标签</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            placeholder='用逗号分隔，最多 8 个'
                            disabled={busy}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <Separator />
                <FormField
                  control={form.control}
                  name='instructions'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>工作指令</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={14}
                          className='min-h-64'
                          maxLength={64000}
                          placeholder='说明工作目标、步骤、输出要求和边界。'
                          disabled={busy}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <Separator />
                {(['skills', 'connectors'] as const).map((kind) => (
                  <div className='flex flex-col gap-3' key={kind}>
                    <div className='flex items-center justify-between gap-3'>
                      <h2 className='font-medium'>
                        {kind === 'skills' ? '技能' : '连接器'}
                      </h2>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        disabled={busy || (values[kind]?.length ?? 0) >= 32}
                        onClick={() => setPicker(kind)}
                      >
                        <Plus />
                        {kind === 'skills' ? '添加技能' : '添加连接器'}
                      </Button>
                    </div>
                    {form.getValues(kind).map((ref, index) => (
                      <DependencyCard
                        key={ref.key}
                        reference={ref}
                        disabled={busy}
                        onRequiredChange={(value) =>
                          form.setValue(`${kind}.${index}.required`, value, {
                            shouldDirty: true,
                          })
                        }
                        onLoadChange={(value) =>
                          form.setValue(`skills.${index}.load`, value, {
                            shouldDirty: true,
                          })
                        }
                        onToolsChange={(value) =>
                          form.setValue(`connectors.${index}.tools`, value, {
                            shouldDirty: true,
                          })
                        }
                        onRemove={() => {
                          if (kind === 'skills')
                            form.setValue(
                              'skills',
                              form
                                .getValues('skills')
                                .filter((_, i) => i !== index),
                              { shouldDirty: true }
                            )
                          else
                            form.setValue(
                              'connectors',
                              form
                                .getValues('connectors')
                                .filter((_, i) => i !== index),
                              { shouldDirty: true }
                            )
                        }}
                      />
                    ))}
                    {!form.getValues(kind).length && (
                      <p className='text-sm text-muted-foreground'>
                        尚未添加{kind === 'skills' ? '技能' : '连接器'}
                      </p>
                    )}
                  </div>
                ))}
                <Separator />
                <FormField
                  control={form.control}
                  name='starters_text'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>开场问题</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={4}
                          placeholder='每行一个，最多 6 个'
                          disabled={busy}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {expert && (
                  <>
                    {expert.current_release && expert.dependency_issues > 0 && (
                      <Alert>
                        <AlertTitle>
                          当前发布有 {expert.dependency_issues} 项依赖需要检查
                        </AlertTitle>
                        <AlertDescription>
                          必需依赖未就绪会阻止准备，可选依赖可以跳过。
                          修改草稿后仍需另行发布。
                        </AlertDescription>
                      </Alert>
                    )}
                    <Checks check={expert.check} />
                    <DependencyRecoveryNotice command={command} />
                    {expert.check.dependencies.some(
                      (d) =>
                        d.kind === 'skills' &&
                        (d.update_available || d.status === 'version_conflict')
                    ) && (
                      <Button
                        type='button'
                        variant='outline'
                        disabled={busy || dirty}
                        onClick={() => setUpdates(true)}
                      >
                        更新技能引用到草稿
                      </Button>
                    )}
                  </>
                )}
              </form>
            </Form>
            <aside className='min-w-0'>
              <Card>
                <CardHeader>
                  <ResourceIcon
                    image={values.avatar}
                    name={values.name || '专家'}
                    size='lg'
                  />
                  <CardTitle>{values.name || '专家名称'}</CardTitle>
                  <CardDescription>
                    {values.description || '填写简介，说明专家擅长的工作。'}
                  </CardDescription>
                </CardHeader>
                <CardContent className='flex flex-col gap-5'>
                  <div className='flex flex-wrap gap-2'>
                    <Badge variant='secondary'>
                      {categories.data?.find((c) => c.id === values.category)
                        ?.name ?? '未分类'}
                    </Badge>
                    {splitTags(values.tags_text ?? '').map((t, i) => (
                      <Badge variant='outline' key={i}>
                        {t}
                      </Badge>
                    ))}
                  </div>
                  {splitStarters(values.starters_text ?? '').map((s, i) => (
                    <p className='text-sm break-words' key={i}>
                      {s}
                    </p>
                  ))}
                  <Separator />
                  <p className='text-sm text-muted-foreground'>所需能力</p>
                  {[...(values.skills ?? []), ...(values.connectors ?? [])].map(
                    (r) => (
                      <p className='text-sm' key={r.key}>
                        {r.label} · {r.required ? '必须可用' : '可缺省'}
                      </p>
                    )
                  )}
                </CardContent>
              </Card>
            </aside>
          </div>
        </TabsContent>
        <TabsContent
          value='scope'
          forceMount
          hidden={tab !== 'scope'}
          className='pt-4'
        >
          {expert && (
            <Scope
              expert={expert}
              saved={saved}
              disabled={busy}
              onSavingChange={setSavingScope}
            />
          )}
        </TabsContent>
        <TabsContent
          value='versions'
          forceMount
          hidden={tab !== 'versions'}
          className='pt-4'
        >
          {expert && (
            <div className='flex flex-col gap-4'>
              {expert.current_release && (
                <div>
                  <Button
                    variant='outline'
                    disabled={busy || dirty}
                    onClick={() => setWithdraw(true)}
                  >
                    下架专家
                  </Button>
                </div>
              )}
              {expert.releases.length ? (
                expert.releases.map((r) => (
                  <Card key={r.id}>
                    <CardHeader>
                      <CardTitle className='flex items-center gap-3'>
                        v{r.version}
                        {r.id === expert.current_release?.id && (
                          <Badge>当前发布</Badge>
                        )}
                      </CardTitle>
                      <CardDescription>
                        {r.publisher_name} · {dateTime(r.created_at)}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <p className='break-words whitespace-pre-wrap'>
                        {r.release_notes || '无更新说明'}
                      </p>
                    </CardContent>
                  </Card>
                ))
              ) : (
                <p className='text-muted-foreground'>尚未发布版本</p>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
      {picker && (
        <DependencyPicker
          kind={picker}
          close={() => setPicker(undefined)}
          select={(item) => {
            const key = crypto.randomUUID()
            if (picker === 'skills' && item.version_id)
              form.setValue(
                'skills',
                [
                  ...form.getValues('skills'),
                  {
                    key,
                    label: item.name,
                    required: true,
                    load: 'always',
                    skill_id: item.id,
                    version_id: item.version_id,
                    sha256: item.sha256,
                  },
                ],
                { shouldDirty: true }
              )
            else if (picker === 'connectors')
              form.setValue(
                'connectors',
                [
                  ...form.getValues('connectors'),
                  {
                    key,
                    label: item.name,
                    required: true,
                    connector_id: item.id,
                    tools: (item.tools ?? [])
                      .filter((t) => t.enabled)
                      .map((t) => t.key),
                  },
                ],
                { shouldDirty: true }
              )
          }}
        />
      )}
      {publish && expert && (
        <PublishDialog
          expert={expert}
          saved={saved}
          close={() => setPublish(false)}
        />
      )}
      {updates && expert && (
        <SkillReferenceUpdateDialog
          expert={expert}
          feedback={
            <>
              <DependencyRecoveryNotice command={command} />
              {command.error instanceof ApiError &&
                command.error.status === 409 && (
                  <Button
                    type='button'
                    variant='outline'
                    disabled={reloading}
                    onClick={async () => {
                      setReloading(true)
                      try {
                        const result = await api<Expert>(
                          `/experts/${expert.id}`
                        )
                        form.reset(defaults(result))
                        saved(result)
                        setUpdates(false)
                        command.resetError()
                      } catch (e) {
                        command.reportError(e)
                      } finally {
                        setReloading(false)
                      }
                    }}
                  >
                    重新载入草稿后预览
                  </Button>
                )}
            </>
          }
          disabled={
            reloading || command.busy || !!command.pending || command.forbidden
          }
          close={() => setUpdates(false)}
          submit={(changes) =>
            command.execute({
              kind: 'expert.refresh_skills',
              revision: expert.revision,
              changes,
            })
          }
        />
      )}
      {withdraw && expert && (
        <ConfirmDialog
          open
          title='下架专家'
          desc='下架后成员无法新召唤，历史发布与草稿会保留。'
          confirmText='确认下架'
          cancelBtnText='取消'
          destructive
          isLoading={withdrawing}
          onOpenChange={(open) => !open && !withdrawing && setWithdraw(false)}
          handleConfirm={async () => {
            setWithdrawing(true)
            try {
              saved(
                await api<Expert>(
                  `/experts/${expert.id}/withdraw`,
                  'POST',
                  { revision: expert.revision },
                  csrf
                )
              )
              setWithdraw(false)
              toast.success('专家已下架')
            } catch (e) {
              setError(e)
            } finally {
              setWithdrawing(false)
            }
          }}
        />
      )}
    </PageShell>
  )
}

export function ExpertEditor({ expertId }: { expertId?: string }) {
  const { key, refresh } = useExperts()
  const client = useQueryClient()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: [...key, 'detail', expertId],
    enabled: !!expertId,
    queryFn: ({ signal }) =>
      api<Expert>(`/experts/${expertId}`, 'GET', undefined, undefined, signal),
    refetchOnWindowFocus: false,
  })
  function saved(expert: Expert) {
    client.setQueryData([...key, 'detail', expert.id], expert)
    void refresh()
    if (!expertId)
      void navigate({
        to: '/experts/$expertId',
        params: { expertId: expert.id },
        replace: true,
      })
  }
  if (!expertId) return <Editor saved={saved} />
  if (query.isPending)
    return (
      <PageShell title='专家'>
        <LoadingState />
      </PageShell>
    )
  if (query.isError)
    return (
      <PageShell title='专家'>
        <RequestError error={query.error} retry={() => void query.refetch()} />
      </PageShell>
    )
  return (
    <Editor
      key={[...key, query.data.id].join(':')}
      expert={query.data}
      saved={saved}
    />
  )
}
