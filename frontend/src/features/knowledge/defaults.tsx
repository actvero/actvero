import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, dateTime, messageOf, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Field,
  FieldContent,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { Choice } from './controls'
import {
  defaultsPath,
  useKnowledge,
  useKnowledgeData,
  type Defaults,
} from './shared'

type Credential = Schema['CredentialView']

export function KnowledgeDefaults() {
  const query = useKnowledgeData<Defaults>(defaultsPath)
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <div className='flex w-full max-w-4xl flex-col gap-5'>
      <ModelDefaults data={query.data} />
      <ParserCredentials credentials={query.data.credentials} />
    </div>
  )
}

function ModelDefaults({ data }: { data: Defaults }) {
  const { csrf, key, refresh } = useKnowledge()
  const client = useQueryClient()
  const queryKey = [...key, defaultsPath]
  const save = useMutation({
    mutationFn: (settings: Schema['KnowledgeDefaults']) =>
      api<Defaults>(defaultsPath, 'PUT', settings, csrf),
    onSuccess: async (saved) => {
      await client.cancelQueries({ queryKey, exact: true })
      client.setQueryData<Defaults>(queryKey, (current) =>
        current && current.version > saved.version ? current : saved
      )
      toast.success('默认配置已保存')
      await refresh()
    },
    onError: async (error) => {
      toast.error(
        error instanceof ApiError && error.status === 409
          ? '配置已被修改，请确认当前值后重新选择。'
          : `未保存。${messageOf(error)}`
      )
      await client.invalidateQueries({ queryKey, exact: true })
    },
  })
  const settings = save.isPending ? save.variables : data
  const embedding = settings.embedding_model_id ?? 'none'
  const rerank = settings.rerank_enabled
    ? (settings.rerank_model_id ?? 'none')
    : 'none'
  const embeddingOptions = data.models
    .filter((model) => model.kind === 'embedding')
    .map((model) => ({
      value: model.id,
      label: model.dimensions
        ? `${model.name} · ${model.dimensions} 维`
        : model.name,
    }))
  const rerankOptions = data.models
    .filter((model) => model.kind === 'rerank')
    .map((model) => ({ value: model.id, label: model.name }))
  const missingEmbedding =
    embedding !== 'none' &&
    !embeddingOptions.some(({ value }) => value === embedding)
  const missingRerank =
    rerank !== 'none' && !rerankOptions.some(({ value }) => value === rerank)
  function updateModel(kind: 'embedding' | 'rerank', value: string) {
    if (save.isPending || value === (kind === 'embedding' ? embedding : rerank))
      return
    const modelId = value === 'none' ? null : value
    save.mutate({
      version: data.version,
      embedding_model_id:
        kind === 'embedding' ? modelId : data.embedding_model_id,
      rerank_model_id: kind === 'rerank' ? modelId : data.rerank_model_id,
      rerank_enabled:
        kind === 'rerank' ? modelId !== null : data.rerank_enabled,
    })
  }

  return (
    <Card className='gap-4 py-4 shadow-none'>
      <CardHeader layout='row' className='justify-between px-4 sm:px-5'>
        <CardTitle>索引与检索</CardTitle>
        <span role='status' className='text-sm text-muted-foreground'>
          {save.isPending && '正在保存…'}
        </span>
      </CardHeader>
      <CardContent className='px-4 sm:px-5'>
        <FieldGroup className='gap-0 divide-y'>
          <Field className='grid gap-2 pb-3 @md/field-group:grid-cols-[9rem_minmax(0,1fr)]'>
            <FieldTitle className='@md/field-group:self-center'>
              向量模型
            </FieldTitle>
            <FieldContent className='min-w-0 [&>[data-slot=select-trigger]]:w-full'>
              <Choice
                label='向量模型'
                value={embedding}
                onChange={(value) => updateModel('embedding', value)}
                disabled={save.isPending}
                items={[
                  { value: 'none', label: '暂不配置' },
                  ...(missingEmbedding
                    ? [{ value: embedding, label: '当前向量模型已不可选' }]
                    : []),
                  ...embeddingOptions,
                ]}
              />
            </FieldContent>
          </Field>
          <Field className='grid gap-2 pt-3 @md/field-group:grid-cols-[9rem_minmax(0,1fr)]'>
            <FieldTitle className='@md/field-group:self-center'>
              重排序
            </FieldTitle>
            <FieldContent className='min-w-0 [&>[data-slot=select-trigger]]:w-full'>
              <Choice
                label='重排序'
                value={rerank}
                onChange={(value) => updateModel('rerank', value)}
                disabled={save.isPending}
                items={[
                  { value: 'none', label: '不启用' },
                  ...(missingRerank
                    ? [{ value: rerank, label: '当前重排序模型已不可选' }]
                    : []),
                  ...rerankOptions,
                ]}
              />
            </FieldContent>
          </Field>
        </FieldGroup>
        {(missingEmbedding || missingRerank) && (
          <FieldError className='mt-3'>请重新选择不可用的模型。</FieldError>
        )}
      </CardContent>
    </Card>
  )
}

function rateLimitEnd(credential: Credential) {
  return credential.enabled &&
    credential.error === '官方账号限流，等待恢复' &&
    credential.cooldown_until
    ? Date.parse(credential.cooldown_until)
    : 0
}

function CredentialStatus({
  credential,
  now,
}: {
  credential: Credential
  now: number
}) {
  if (!credential.enabled)
    return credential.error === '凭据无效或无权访问，请更新 Key' ? (
      <Badge variant='destructive'>凭据失效</Badge>
    ) : (
      <Badge variant='secondary'>已停用</Badge>
    )
  if (rateLimitEnd(credential) > now && credential.cooldown_until)
    return (
      <div className='flex flex-wrap items-center gap-1.5'>
        <Badge variant='outline' className='border-warning/30 bg-warning/10'>
          限流恢复中
        </Badge>
        <time
          dateTime={credential.cooldown_until}
          className='text-xs text-muted-foreground'
        >
          {dateTime(credential.cooldown_until)} 恢复
        </time>
      </div>
    )
  return <Badge variant='secondary'>已保存</Badge>
}

function ParserCredentials({ credentials }: { credentials: Credential[] }) {
  const { csrf, refresh } = useKnowledge()
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const recoveries = credentials.map(rateLimitEnd).filter((end) => end > now)
    if (!recoveries.length) return
    const next = Math.min(...recoveries)
    const timer = window.setTimeout(
      () => setNow(Date.now()),
      Math.max(0, next - Date.now())
    )
    return () => window.clearTimeout(timer)
  }, [credentials, now])

  const toggle = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) =>
      api(
        `/knowledge/credentials/${id}?enabled=${value}`,
        'PUT',
        undefined,
        csrf
      ),
    onSuccess: async () => {
      await refresh()
    },
    onError: (error) => toast.error(messageOf(error)),
  })
  return (
    <Card className='gap-3 py-4 shadow-none'>
      <CardHeader
        layout='row'
        className='flex-wrap justify-between gap-3 sm:px-5'
      >
        <CardTitle>文档解析</CardTitle>
        <AddCredentials />
      </CardHeader>
      <CardContent className='px-4 sm:px-5'>
        {credentials.length ? (
          <div className='overflow-hidden rounded-md border'>
            <Table>
              <TableHeader className='bg-muted/40'>
                <TableRow>
                  <TableHead className='px-3'>MinerU Key 名称</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className='w-16 text-center'>启用</TableHead>
                  <TableHead className='w-10'>
                    <span className='sr-only'>操作</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {credentials.map((credential) => (
                  <TableRow key={credential.id}>
                    <TableCell className='px-3 font-medium'>
                      <div className='max-w-44 break-words whitespace-normal'>
                        {credential.name}
                      </div>
                    </TableCell>
                    <TableCell className='whitespace-normal'>
                      <CredentialStatus credential={credential} now={now} />
                    </TableCell>
                    <TableCell className='text-center'>
                      <Switch
                        aria-label={`启用 ${credential.name}`}
                        checked={credential.enabled}
                        disabled={toggle.isPending}
                        onCheckedChange={(value) =>
                          toggle.mutate({ id: credential.id, value })
                        }
                      />
                    </TableCell>
                    <TableCell className='text-end'>
                      <CredentialActions credential={credential} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className='rounded-md border border-dashed p-4 text-sm text-muted-foreground'>
            尚未添加 MinerU Key。
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function AddCredentials() {
  const { csrf, refresh } = useKnowledge()
  const [open, setOpen] = useState(false)
  const [secret, setSecret] = useState('')
  const [name, setName] = useState('')
  const keys = secret
    .split(/[,，\n]+/)
    .map((key) => key.trim())
    .filter(Boolean)
  const add = useMutation({
    mutationFn: () =>
      api(
        '/knowledge/credentials/batch',
        'POST',
        { name: name.trim() || null, keys },
        csrf
      ),
    onSuccess: async () => {
      setSecret('')
      setName('')
      setOpen(false)
      toast.success('解析凭据已保存')
      await refresh()
    },
  })
  function changeOpen(value: boolean) {
    if (add.isPending) return
    if (!value) {
      setSecret('')
      setName('')
      add.reset()
    }
    setOpen(value)
  }
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' disabled={add.isPending}>
          <Plus data-icon='inline-start' />
          添加 Key
        </Button>
      </DialogTrigger>
      <DialogContent showCloseButton={!add.isPending}>
        <DialogHeader>
          <DialogTitle>添加 MinerU Key</DialogTitle>
          <DialogDescription className='sr-only'>
            设置凭据名称并输入 API Key
          </DialogDescription>
        </DialogHeader>
        <form
          className='flex min-w-0 flex-col gap-4'
          onSubmit={(event) => {
            event.preventDefault()
            if (keys.length && !add.isPending) add.mutate()
          }}
        >
          <Field>
            <FieldLabel htmlFor='mineru-key-name'>名称</FieldLabel>
            <Input
              id='mineru-key-name'
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={97}
              placeholder='选填，批量添加时自动编号'
              disabled={add.isPending}
            />
          </Field>
          <Field data-invalid={!!add.error}>
            <FieldLabel htmlFor='mineru-keys'>API Key</FieldLabel>
            <Input
              id='mineru-keys'
              type='password'
              placeholder='多个 Key 用逗号分隔'
              autoComplete='off'
              spellCheck={false}
              aria-invalid={!!add.error}
              aria-describedby={add.error ? 'mineru-key-error' : undefined}
              value={secret}
              onChange={(event) => {
                setSecret(event.target.value)
                if (add.error) add.reset()
              }}
              maxLength={81940}
              disabled={add.isPending}
              required
            />
            {add.error && (
              <FieldError id='mineru-key-error'>
                {messageOf(add.error)}
              </FieldError>
            )}
          </Field>
          <DialogFooter>
            <DialogClose asChild>
              <Button type='button' variant='outline' disabled={add.isPending}>
                取消
              </Button>
            </DialogClose>
            <Button type='submit' disabled={add.isPending || !keys.length}>
              {add.isPending ? '正在添加…' : '添加 Key'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CredentialActions({ credential }: { credential: Credential }) {
  const { csrf, refresh } = useKnowledge()
  const trigger = useRef<HTMLButtonElement>(null)
  const [action, setAction] = useState<'edit' | 'delete' | null>(null)
  const [name, setName] = useState(credential.name)
  const rename = useMutation({
    mutationFn: () =>
      api(
        `/knowledge/credentials/${credential.id}`,
        'PATCH',
        { name: name.trim() },
        csrf
      ),
    onSuccess: async () => {
      setAction(null)
      await refresh()
      toast.success('名称已更新')
    },
  })
  const remove = useMutation({
    mutationFn: () =>
      api(`/knowledge/credentials/${credential.id}`, 'DELETE', undefined, csrf),
    onSuccess: async () => {
      await refresh()
      setAction(null)
      toast.success('Key 已删除')
    },
  })
  function restoreFocus(event: Event) {
    event.preventDefault()
    trigger.current?.focus()
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={trigger}
            type='button'
            variant='ghost'
            size='icon-sm'
            aria-label={`${credential.name} 操作`}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align='end'
          onCloseAutoFocus={(event) => {
            if (action) event.preventDefault()
          }}
        >
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() => {
                setName(credential.name)
                rename.reset()
                setAction('edit')
              }}
            >
              <Pencil />
              编辑
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant='destructive'
              onSelect={() => {
                remove.reset()
                setAction('delete')
              }}
            >
              <Trash2 />
              删除
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={action === 'edit'}
        onOpenChange={(open) => {
          if (!open && !rename.isPending) setAction(null)
        }}
      >
        <DialogContent
          showCloseButton={!rename.isPending}
          onCloseAutoFocus={restoreFocus}
        >
          <DialogHeader>
            <DialogTitle>修改 Key 名称</DialogTitle>
            <DialogDescription className='sr-only'>
              更新 MinerU 凭据的显示名称
            </DialogDescription>
          </DialogHeader>
          <form
            className='flex flex-col gap-4'
            onSubmit={(event) => {
              event.preventDefault()
              if (
                name.trim() &&
                name.trim() !== credential.name &&
                !rename.isPending
              )
                rename.mutate()
            }}
          >
            <Field data-invalid={!!rename.error}>
              <FieldLabel htmlFor='rename-mineru-key'>名称</FieldLabel>
              <Input
                id='rename-mineru-key'
                value={name}
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                disabled={rename.isPending}
                aria-invalid={!!rename.error}
                aria-describedby={
                  rename.error ? 'rename-mineru-key-error' : undefined
                }
                required
              />
              {rename.error && (
                <FieldError id='rename-mineru-key-error'>
                  {messageOf(rename.error)}
                </FieldError>
              )}
            </Field>
            <DialogFooter>
              <DialogClose asChild>
                <Button
                  type='button'
                  variant='outline'
                  disabled={rename.isPending}
                >
                  取消
                </Button>
              </DialogClose>
              <Button
                type='submit'
                disabled={
                  rename.isPending ||
                  !name.trim() ||
                  name.trim() === credential.name
                }
              >
                {rename.isPending ? '正在保存…' : '保存名称'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={action === 'delete'}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setAction(null)
        }}
        onCloseAutoFocus={restoreFocus}
        title='删除 MinerU Key？'
        desc={`删除「${credential.name}」后，知识库将无法再使用此 Key 解析文档。`}
        cancelBtnText='取消'
        confirmText={remove.isPending ? '正在删除…' : '删除'}
        destructive
        isLoading={remove.isPending}
        handleConfirm={() => remove.mutate()}
      >
        {remove.error && <FieldError>{messageOf(remove.error)}</FieldError>}
      </ConfirmDialog>
    </>
  )
}
