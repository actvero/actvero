import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowLeft,
  Download,
  FileText,
  FolderOpen,
  History,
  Settings2,
  Upload,
  UserRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, dateTime, messageOf, type Schema } from '@/lib/api'
import { useReturnFocus } from '@/hooks/use-return-focus'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageShell } from '@/components/layout/page-shell'
import { Markdown } from '@/components/markdown'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { DependencyRecoveryNotice } from '@/features/experts/dependency-command'
import { useExperts } from '@/features/experts/shared'
import { SkillExpertImpact } from '@/features/experts/skill-impact'
import { useDependencyCommand } from '@/features/experts/use-dependency-command'
import { CompareDialog } from './compare-dialog'
import { FileBrowser } from './file-tree'
import { MetadataDialog } from './metadata-dialog'
import {
  downloadSkill,
  scopeLabels,
  categoryLabel,
  sizeLabel,
  useSkills,
  versionAction,
  type Skill,
  type SkillFile,
  type Version,
} from './shared'
import { SkillStatusBadge } from './status-badge'

function Overview({
  skillId,
  versionId,
}: {
  skillId: string
  versionId: string
}) {
  const { key } = useSkills()
  const query = useQuery({
    queryKey: [...key, skillId, versionId, 'overview'],
    queryFn: ({ signal }) =>
      api<Schema['SkillOverview']>(
        `/skills/${skillId}/versions/${versionId}/overview`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return query.isPending ? (
    <LoadingState />
  ) : query.isError ? (
    <RequestError error={query.error} retry={() => void query.refetch()} />
  ) : (
    <Card>
      <CardHeader>
        <p className='text-xs tracking-widest text-muted-foreground'>
          来源：SKILL.MD
        </p>
      </CardHeader>
      <CardContent>
        <Markdown>{query.data.content || '此版本暂无正文。'}</Markdown>
      </CardContent>
    </Card>
  )
}
function FilePreview({
  skillId,
  versionId,
  file,
  close,
}: {
  skillId: string
  versionId: string
  file: SkillFile
  close: () => void
}) {
  const restoreFocus = useReturnFocus()
  const { key } = useSkills()
  const isMarkdown = /\.(md|markdown|mdown)$/i.test(file.path)
  const query = useQuery({
    queryKey: [...key, skillId, versionId, 'file', file.path],
    enabled: file.previewable,
    queryFn: ({ signal }) =>
      api<Schema['SkillFileContent']>(
        `/skills/${skillId}/versions/${versionId}/file?${new URLSearchParams({ path: file.path })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <Dialog open onOpenChange={(v) => !v && close()}>
      <DialogContent
        onCloseAutoFocus={restoreFocus}
        className='max-h-[90dvh] overflow-y-auto sm:max-w-4xl'
      >
        <DialogHeader>
          <DialogTitle className='break-all'>{file.path}</DialogTitle>
          <DialogDescription>
            {sizeLabel(file.size)} · 只读预览
          </DialogDescription>
        </DialogHeader>
        {!file.previewable ? (
          <p className='text-sm text-muted-foreground'>
            此文件不支持文本预览，请下载技能包后查看。
          </p>
        ) : query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : isMarkdown ? (
          <Tabs defaultValue='preview' className='min-w-0'>
            <TabsList aria-label='Markdown 查看方式'>
              <TabsTrigger value='preview'>预览</TabsTrigger>
              <TabsTrigger value='source'>源码</TabsTrigger>
            </TabsList>
            <TabsContent
              value='preview'
              className='max-h-[65dvh] min-w-0 overflow-auto'
            >
              <Markdown>
                {query.data.content.replace(
                  /^\uFEFF?---\r?\n[A-Za-z_][\w-]*:[\s\S]*?\r?\n---(?:\r?\n|$)/,
                  ''
                )}
              </Markdown>
            </TabsContent>
            <TabsContent
              value='source'
              className='max-h-[65dvh] min-w-0 overflow-auto'
            >
              <pre className='overflow-x-auto rounded-md bg-muted p-4 text-xs leading-6'>
                {query.data.content}
              </pre>
            </TabsContent>
          </Tabs>
        ) : (
          <pre className='overflow-x-auto rounded-md bg-muted p-4 text-xs leading-6'>
            {query.data.content}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}
type PendingAction = {
  version: Version
  revision: number
  action: Schema['SkillAction']['action'] | 'delete'
}
const actionLabels = {
  publish: '发布版本',
  withdraw: '下架版本',
  delete: '删除草稿',
}

export function SkillDetail({ skillId }: { skillId: string }) {
  const { key } = useSkills()
  const query = useQuery({
    queryKey: [...key, skillId],
    queryFn: ({ signal }) =>
      api<Skill>(`/skills/${skillId}`, 'GET', undefined, undefined, signal),
  })
  return (
    <PageShell>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <DetailContent skill={query.data} key={[...key, skillId].join(':')} />
      )}
    </PageShell>
  )
}
function DetailContent({ skill }: { skill: Skill }) {
  const { csrf, refresh } = useSkills()
  const { refresh: refreshExperts } = useExperts()
  const [draftUpdates, setDraftUpdates] = useState<
    Schema['ExpertDraftSelection'][]
  >([])
  const [impactDenied, setImpactDenied] = useState(false)
  const denyImpact = useCallback(() => {
    setImpactDenied(true)
    setDraftUpdates([])
  }, [])
  const [tab, setTab] = useState('overview')
  const [expandedDescription, setExpandedDescription] = useState(false)
  const [selected, setSelected] = useState<string>()
  const [file, setFile] = useState<SkillFile>()
  const [settings, setSettings] = useState(false)
  const [compare, setCompare] = useState<Version>()
  const [pending, setPending] = useState<PendingAction>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const command = useDependencyCommand(
    skill.id,
    'skill.publish',
    async (isLive) => {
      await Promise.all([refresh(), refreshExperts()])
      if (!isLive()) return
      setPending(undefined)
      setDraftUpdates([])
      toast.success('发布与所选草稿更新已完成')
    }
  )
  const activeVersion = skill.versions.find(
    (v) => v.id === skill.default_version_id && v.status === 'published'
  )
  const version =
    skill.versions.find((v) => v.id === selected) ??
    activeVersion ??
    skill.versions[0]
  async function confirm() {
    if (!pending) return
    setBusy(true)
    setError(undefined)
    try {
      if (pending.action === 'delete')
        await api(
          `/skills/${skill.id}/versions/${pending.version.id}?revision=${skill.revision}`,
          'DELETE',
          undefined,
          csrf
        )
      else if (pending.action === 'publish' && draftUpdates.length) {
        await command.execute({
          kind: 'skill.publish',
          version_id: pending.version.id,
          revision: pending.revision,
          draft_updates: draftUpdates,
        })
        return
      } else
        await versionAction(
          { ...skill, revision: pending.revision },
          pending.version,
          pending.action,
          csrf
        )
      await refresh()
      if (pending.action === 'publish') {
        setSelected(pending.version.id)
        setFile(undefined)
      }
      toast.success(actionLabels[pending.action] + '成功')
      setPending(undefined)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  function requestAction(v: Version, action: PendingAction['action']) {
    if (command.pending || command.forbidden || impactDenied) return
    setError(undefined)
    setDraftUpdates([])
    setPending({ version: v, revision: skill.revision, action })
  }
  async function download() {
    if (!version) return
    setBusy(true)
    try {
      await downloadSkill(skill, version, csrf)
      await refresh()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }
  if (command.forbidden) return <RequestError error={command.error} />
  return (
    <>
      <DependencyRecoveryNotice command={command} />
      <div>
        <Button variant='ghost' asChild>
          <Link to='/skills'>
            <ArrowLeft />
            返回技能管理
          </Link>
        </Button>
      </div>
      <div className='flex min-w-0 flex-col gap-8 lg:grid lg:grid-cols-[minmax(0,1fr)_19rem] lg:items-start xl:grid-cols-[minmax(0,1fr)_22rem]'>
        <section className='contents min-w-0 lg:block lg:space-y-8'>
          <div className='order-1 space-y-5'>
            <div className='flex flex-wrap gap-2'>
              {version ? (
                <SkillStatusBadge status={version.status} />
              ) : (
                <Badge variant='secondary'>暂无版本</Badge>
              )}
              <Badge variant='outline'>{scopeLabels[skill.audience]}</Badge>
              <Badge variant='outline'>{categoryLabel(skill)}</Badge>
            </div>
            <div className='flex items-center gap-4'>
              <ResourceIcon
                image={skill.icon?.image}
                name={skill.display_name}
                size='lg'
              />
              <div className='min-w-0 space-y-2'>
                <h1 className='text-3xl font-bold tracking-tight break-words sm:text-4xl'>
                  {skill.display_name}
                </h1>
                {skill.display_name !== skill.name && (
                  <p className='font-mono text-sm break-all text-muted-foreground'>
                    {skill.name}
                  </p>
                )}
              </div>
            </div>
            {version && (
              <div className='flex items-center gap-2 text-sm text-muted-foreground'>
                <UserRound className='size-4' />
                <span>上传者 {version.uploader_name}</span>
              </div>
            )}
            <div className='space-y-2'>
              <p
                id='skill-description'
                className={`max-w-3xl text-base leading-8 break-words text-muted-foreground ${expandedDescription ? '' : 'line-clamp-3'}`}
              >
                {skill.description}
              </p>
              {skill.description.length > 300 && (
                <Button
                  variant='ghost'
                  size='sm'
                  aria-expanded={expandedDescription}
                  aria-controls='skill-description'
                  onClick={() => setExpandedDescription((v) => !v)}
                >
                  {expandedDescription ? '收起简介' : '展开简介'}
                </Button>
              )}
            </div>
          </div>
          <Tabs
            value={tab}
            onValueChange={setTab}
            className='order-3 min-w-0 gap-6'
          >
            <TabsList variant='line'>
              <TabsTrigger value='overview'>概览</TabsTrigger>
              <TabsTrigger value='files'>文件</TabsTrigger>
              <TabsTrigger value='versions'>版本</TabsTrigger>
            </TabsList>
            <TabsContent value='overview'>
              {version ? (
                <Overview skillId={skill.id} versionId={version.id} />
              ) : (
                <p className='py-12 text-center text-muted-foreground'>
                  还没有版本，请上传技能包。
                </p>
              )}
            </TabsContent>
            <TabsContent value='files'>
              {version ? (
                <Card>
                  <CardHeader>
                    <CardTitle className='flex items-center justify-between gap-2'>
                      <span className='flex items-center gap-2'>
                        <FolderOpen className='size-4' />
                        文件浏览
                      </span>
                      <Badge variant='secondary'>{version.files.length}</Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <FileBrowser files={version.files} onSelect={setFile} />
                  </CardContent>
                </Card>
              ) : (
                <p className='py-12 text-center text-muted-foreground'>
                  暂无文件
                </p>
              )}
            </TabsContent>
            <TabsContent value='versions'>
              <div className='space-y-4'>
                {skill.versions.map((v) => (
                  <Card key={v.id}>
                    <CardContent className='space-y-4'>
                      <div className='flex flex-wrap items-center justify-between gap-4'>
                        <div className='flex flex-wrap items-center gap-2'>
                          <span className='font-mono font-semibold'>
                            v{v.version}
                          </span>
                          <SkillStatusBadge status={v.status} />
                          {version?.id === v.id && (
                            <Badge variant='secondary'>当前查看</Badge>
                          )}
                        </div>
                        <span className='text-xs text-muted-foreground'>
                          {dateTime(v.created_at)}
                        </span>
                      </div>
                      {v.release_notes && (
                        <p className='text-sm whitespace-pre-wrap text-muted-foreground'>
                          {v.release_notes}
                        </p>
                      )}
                      <div className='flex flex-wrap items-center justify-between gap-4'>
                        <span className='text-xs text-muted-foreground'>
                          {v.files.length} 个文件 · {sizeLabel(v.size)} ·{' '}
                          {v.uploader_name}
                        </span>
                        <div className='flex flex-wrap gap-2'>
                          <Button
                            variant='outline'
                            size='sm'
                            onClick={() => {
                              setSelected(v.id)
                              setTab('overview')
                            }}
                          >
                            查看内容
                          </Button>
                          {skill.versions.length > 1 && (
                            <Button
                              variant='outline'
                              size='sm'
                              onClick={() => setCompare(v)}
                            >
                              对比版本
                            </Button>
                          )}
                          {v.status !== 'published' ? (
                            <Button
                              size='sm'
                              onClick={() => requestAction(v, 'publish')}
                            >
                              {v.status === 'withdrawn' ||
                              v.status === 'superseded'
                                ? '重新发布'
                                : '发布'}
                            </Button>
                          ) : null}
                          {(v.status === 'published' ||
                            v.status === 'superseded') && (
                            <Button
                              variant='ghost'
                              size='sm'
                              onClick={() => requestAction(v, 'withdraw')}
                              aria-label={`下架 v${v.version}`}
                            >
                              下架
                            </Button>
                          )}
                          {v.status === 'draft' && (
                            <Button
                              variant='ghost'
                              size='sm'
                              onClick={() => requestAction(v, 'delete')}
                            >
                              删除草稿
                            </Button>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
                {!skill.versions.length && (
                  <p className='py-12 text-center text-muted-foreground'>
                    暂无版本
                  </p>
                )}
              </div>
            </TabsContent>
          </Tabs>
        </section>
        <aside className='order-2 min-w-0 space-y-5 lg:order-none'>
          {version && (
            <Card className='hidden lg:flex'>
              <CardHeader>
                <CardTitle className='flex items-center justify-between'>
                  <span className='flex items-center gap-2'>
                    <FolderOpen className='size-4' />
                    文件浏览
                  </span>
                  <span className='text-sm text-muted-foreground'>
                    {version.files.length}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <FileBrowser files={version.files} onSelect={setFile} />
              </CardContent>
            </Card>
          )}
          <Card>
            <CardContent className='space-y-5'>
              <div className='flex items-center justify-between gap-3'>
                <span className='text-sm text-muted-foreground'>查看版本</span>
                {version ? (
                  <Select
                    value={version.id}
                    onValueChange={(v) => {
                      setSelected(v)
                      setFile(undefined)
                    }}
                  >
                    <SelectTrigger className='w-36' aria-label='查看版本'>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {skill.versions.map((v) => (
                        <SelectItem key={v.id} value={v.id}>
                          v{v.version}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <span>暂无</span>
                )}
              </div>
              <Separator />
              <dl className='space-y-5 text-sm'>
                <div className='flex justify-between gap-4'>
                  <dt className='text-muted-foreground'>分发次数</dt>
                  <dd>{skill.downloads}</dd>
                </div>
                <Separator />
                <div className='flex justify-between gap-4'>
                  <dt className='text-muted-foreground'>使用范围</dt>
                  <dd>
                    {scopeLabels[skill.audience]}
                    {skill.audience === 'selected' &&
                      ` · ${skill.member_ids.length} 人`}
                  </dd>
                </div>
                <Separator />
                <div className='flex justify-between gap-4'>
                  <dt className='text-muted-foreground'>生效版本</dt>
                  <dd>
                    {activeVersion
                      ? `v${activeVersion.version}`
                      : '暂无生效版本'}
                  </dd>
                </div>
                {version && (
                  <>
                    <Separator />
                    <div className='flex justify-between gap-4'>
                      <dt className='text-muted-foreground'>技能包大小</dt>
                      <dd>{sizeLabel(version.size)}</dd>
                    </div>
                  </>
                )}
              </dl>
            </CardContent>
          </Card>
          {version && (
            <Card>
              <CardHeader>
                <CardTitle className='flex items-center gap-2'>
                  <Download className='size-4' />
                  获取技能
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-4'>
                <Button
                  className='w-full'
                  disabled={busy}
                  onClick={() => void download()}
                >
                  <Download />
                  {busy ? '处理中…' : '下载技能包'}
                </Button>
                <p className='text-xs leading-5 text-muted-foreground'>
                  {version.status === 'published'
                    ? '下载当前生效版本的原始 ZIP。'
                    : '此版本未生效，仅管理员可下载检查。'}
                </p>
                <details className='text-xs text-muted-foreground'>
                  <summary className='cursor-pointer'>SHA-256 校验值</summary>
                  <p className='mt-2 font-mono break-all'>{version.sha256}</p>
                </details>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>管理</CardTitle>
            </CardHeader>
            <CardContent className='flex flex-col gap-2'>
              <Button variant='outline' className='justify-start' asChild>
                <Link to='/skills/upload' search={{ skill: skill.id }}>
                  <Upload />
                  上传新版本
                </Link>
              </Button>
              <Button
                variant='outline'
                className='justify-start'
                onClick={() => setSettings(true)}
              >
                <Settings2 />
                展示资料与使用范围
              </Button>
              <Button variant='outline' className='justify-start' asChild>
                <Link to='/skill-distributions' search={{ skill: skill.id }}>
                  <History />
                  分发记录
                </Link>
              </Button>
              {version && version.status !== 'published' && (
                <Button onClick={() => requestAction(version, 'publish')}>
                  <FileText />
                  发布此版本
                </Button>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
      {compare &&
        skill.versions.length > 1 &&
        skill.versions.some((v) => v.id === compare.id) && (
          <CompareDialog
            key={skill.versions.map((v) => v.id).join(',')}
            skill={skill}
            target={compare}
            close={() => setCompare(undefined)}
          />
        )}
      {settings && (
        <MetadataDialog skill={skill} close={() => setSettings(false)} />
      )}
      {file && version && (
        <FilePreview
          skillId={skill.id}
          versionId={version.id}
          file={file}
          close={() => setFile(undefined)}
        />
      )}
      {pending && (
        <ActionDialog
          open
          title={`${actionLabels[pending.action]} v${pending.version.version}`}
          className='flex max-h-[90dvh] flex-col sm:max-w-2xl'
          confirmText={
            busy || command.busy
              ? '处理中…'
              : draftUpdates.length
                ? `发布并更新 ${draftUpdates.length} 位草稿`
                : actionLabels[pending.action]
          }
          disabled={
            impactDenied ||
            command.forbidden ||
            !!command.pending ||
            (command.error instanceof ApiError && command.error.status === 409)
          }
          cancelBtnText='取消'
          destructive={
            pending.action === 'withdraw' || pending.action === 'delete'
          }
          isLoading={busy || command.busy}
          onOpenChange={(v) =>
            !v && !busy && !command.busy && setPending(undefined)
          }
          handleConfirm={() => void confirm()}
          desc={
            pending.action === 'publish'
              ? `${activeVersion ? `将生效版本从 v${activeVersion.version} 切换为 v${pending.version.version}，原版本保留供获准的历史引用使用。` : `v${pending.version.version} 将成为唯一生效版本。`}“${scopeLabels[skill.audience]}”范围内的成员可获取此版本；已下载的本地副本不自动更新。`
              : pending.action === 'withdraw'
                ? '停止此版本后，其历史采用和专家引用也不可获取；如果停止当前生效版，该技能暂时不可用。历史文件保留供管理员检查。'
                : '删除此草稿及文件，操作无法撤销。'
          }
        >
          <div className='flex min-h-0 flex-col gap-3 overflow-y-auto'>
            {pending.action !== 'delete' && (
              <SkillExpertImpact
                skillId={skill.id}
                targetVersionId={
                  pending.action === 'publish' ? pending.version.id : undefined
                }
                sourceVersionId={
                  pending.action === 'withdraw' ? pending.version.id : undefined
                }
                selected={draftUpdates}
                onChange={
                  pending.action === 'publish' ? setDraftUpdates : undefined
                }
                disabled={
                  busy || command.busy || !!command.pending || command.forbidden
                }
                onForbidden={denyImpact}
              />
            )}
            <DependencyRecoveryNotice command={command} />
            {command.error instanceof ApiError &&
              command.error.status === 409 && (
                <Button
                  type='button'
                  variant='outline'
                  onClick={async () => {
                    await Promise.all([refresh(), refreshExperts()])
                    setDraftUpdates([])
                    setPending(undefined)
                    command.resetError()
                  }}
                >
                  刷新后重新预览
                </Button>
              )}
            {error != null && <RequestError error={error} />}
          </div>
        </ActionDialog>
      )}
    </>
  )
}

function ActionDialog(props: React.ComponentProps<typeof ConfirmDialog>) {
  const restoreFocus = useReturnFocus()
  return <ConfirmDialog {...props} onCloseAutoFocus={restoreFocus} />
}
