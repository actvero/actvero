import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  ChevronDown,
  ChevronRight,
  Play,
  RotateCcw,
  Ellipsis,
  Pencil,
} from 'lucide-react'
import { toast } from 'sonner'
import { type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
  CollapsibleHeader,
} from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { JsonEditor } from '@/components/ui/json-editor'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { RequestError, LoadingState } from '@/components/request-state'
import { TokenEstimate, CopyButton } from './capability-controls'
import { useCapabilities, useTokenCounts } from './capability-data'
import { Presentation } from './presentation'
import { SchemaFields } from './schema-fields'
import {
  parseArguments,
  schemaDefaults,
  supportsForm,
  validateRequired,
  type InputSchema,
} from './schema-utils'
import {
  useDiscovery,
  useReturnFocus,
  useMcp,
  kindNames,
  type Service,
  type Capability,
} from './shared'

export function CapabilityPanel({
  service,
  tab,
  onTab,
}: {
  service: Service
  tab: string
  onTab: (v: string) => void
}) {
  const { write, invalidate } = useMcp()
  const discovery = useDiscovery(service.id)
  const query = useCapabilities(service.id)
  const counts = useTokenCounts(query.data?.items)
  const [search, setSearch] = useState('')
  const [bulk, setBulk] = useState(false)
  async function setAll(enabled: boolean) {
    setBulk(true)
    try {
      for (const c of query.data?.items.filter((c) => c.kind === tab) ?? []) {
        if (c.enabled === enabled) continue
        await write(`/services/${service.id}/policy`, 'PUT', {
          kind: c.kind,
          key: c.key,
          enabled,
          description:
            c.description === c.original_description ? null : c.description,
        })
      }
    } catch {
      toast.error('部分能力未更新，请刷新后重试')
    } finally {
      await invalidate()
      setBulk(false)
    }
  }
  return (
    <div className='flex flex-col gap-4'>
      <Tabs value={tab} onValueChange={onTab}>
        <TabsList className='h-auto max-w-full flex-wrap justify-start'>
          {Object.entries(kindNames).map(([kind, label]) => (
            <TabsTrigger key={kind} value={kind}>
              {label}{' '}
              {query.data
                ? query.data.items.filter((c) => c.kind === kind).length
                : (service.counts[kind] ?? 0)}
            </TabsTrigger>
          ))}
          <TabsTrigger value='presentation'>展示设置</TabsTrigger>
        </TabsList>
        {Object.entries(kindNames).map(([kind, label]) => (
          <TabsContent
            key={kind}
            value={kind}
            className='flex flex-col gap-3 pt-3'
          >
            {query.isPending ? (
              <LoadingState />
            ) : query.isError ? (
              <RequestError
                error={query.error}
                retry={() => void query.refetch()}
              />
            ) : (
              <>
                {!discovery?.connecting &&
                  (discovery?.error || query.data.error) && (
                    <Alert>
                      <AlertDescription>
                        {discovery?.error || query.data.error}
                      </AlertDescription>
                    </Alert>
                  )}
                <div className='flex flex-wrap items-center gap-2'>
                  <Input
                    className='sm:max-w-xs'
                    aria-label={`搜索${label}`}
                    placeholder={`搜索${label}名称或说明…`}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <Button
                    variant='ghost'
                    size='sm'
                    disabled={
                      bulk || !query.data.items.some((c) => c.kind === kind)
                    }
                    onClick={() => void setAll(true)}
                  >
                    全部开启
                  </Button>
                  <Button
                    variant='ghost'
                    size='sm'
                    disabled={
                      bulk || !query.data.items.some((c) => c.kind === kind)
                    }
                    onClick={() => void setAll(false)}
                  >
                    全部关闭
                  </Button>
                </div>
                {query.data.items
                  .filter(
                    (c) =>
                      c.kind === kind &&
                      (c.name + c.description)
                        .toLowerCase()
                        .includes(search.toLowerCase())
                  )
                  .map((c) => (
                    <CapabilityRow
                      key={c.key}
                      item={c}
                      service={service}
                      tokens={counts?.[c.key]}
                      bulk={bulk}
                    />
                  ))}
                {!query.data.items.some((c) => c.kind === kind) && (
                  <div className='py-8 text-center text-sm text-muted-foreground'>
                    {discovery?.connecting ? (
                      <LoadingState />
                    ) : query.data.checked_at ? (
                      `此服务未提供${label}`
                    ) : service.configured ? (
                      '尚未读取能力，请在更多菜单中刷新工具'
                    ) : (
                      '配置凭据或完成授权后自动读取能力'
                    )}
                  </div>
                )}
              </>
            )}
          </TabsContent>
        ))}
        <TabsContent value='presentation' className='pt-3'>
          <Presentation
            key={service.id + ':' + service.version}
            service={service}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function CapabilityRow({
  item,
  service,
  tokens,
  bulk,
}: {
  item: Capability
  service: Service
  tokens?: number
  bulk: boolean
}) {
  const { write, invalidate } = useMcp()
  const [open, setOpen] = useState(false)
  const [run, setRun] = useState(false)
  const [running, setRunning] = useState(false)
  const runTrigger = useRef<HTMLButtonElement>(null)
  const [edit, setEdit] = useState(false)
  const [pending, setPending] = useState(false)
  async function update(enabled: boolean, description: string | null) {
    setPending(true)
    try {
      await write(`/services/${service.id}/policy`, 'PUT', {
        kind: item.kind,
        key: item.key,
        enabled,
        description,
      })
      await invalidate()
      setEdit(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setPending(false)
    }
  }
  return (
    <Collapsible
      open={open}
      onOpenChange={(next) => {
        if (!running) {
          setOpen(next)
          if (next) setRun(false)
        }
      }}
      className='min-w-0 rounded-lg border bg-background'
    >
      <CollapsibleHeader expandOnClick className='overflow-x-auto'>
        <div className='flex min-w-[40rem] items-center gap-3 px-4 py-3'>
          <div className='flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2'>
            <p
              className='max-w-full shrink-0 truncate font-mono text-sm'
              title={item.name}
            >
              {item.name}
            </p>
            <p
              className='max-w-full text-sm [overflow-wrap:anywhere] whitespace-pre-line text-muted-foreground'
              title={item.description}
            >
              {item.description || '暂无说明'}
            </p>
          </div>
          {item.kind === 'tools' && <TokenEstimate count={tokens} />}
          <Switch
            aria-label={`启用 ${item.name}`}
            checked={item.enabled}
            disabled={pending || bulk}
            onCheckedChange={(v) =>
              void update(
                v,
                item.description === item.original_description
                  ? null
                  : item.description
              )
            }
          />
          <Button
            ref={runTrigger}
            variant='outline'
            size='sm'
            disabled={running}
            onClick={() => {
              setRun(true)
              setOpen(true)
            }}
          >
            <Play data-icon='inline-start' />
            {item.kind === 'tools' ? '运行' : '预览'}
          </Button>
          {item.kind !== 'prompts' && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant='ghost'
                  size='icon'
                  aria-label={`更多能力操作 ${item.name}`}
                  disabled={pending || bulk}
                >
                  <Ellipsis />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuGroup>
                  <DropdownMenuItem onSelect={() => setEdit(true)}>
                    <Pencil />
                    编辑说明
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={item.description === item.original_description}
                    onSelect={() => void update(item.enabled, null)}
                  >
                    <RotateCcw />
                    恢复原说明
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <CollapsibleTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              disabled={running}
              aria-label={`${open ? '收起' : '展开'} ${item.name}`}
            >
              {open ? <ChevronDown /> : <ChevronRight />}
            </Button>
          </CollapsibleTrigger>
        </div>
      </CollapsibleHeader>
      <CollapsibleContent forceMount hidden={!open} className='border-t p-4'>
        {run ? (
          <RunPanel
            item={item}
            service={service}
            onBusyChange={setRunning}
            close={() => {
              setOpen(false)
              setRun(false)
              runTrigger.current?.focus()
            }}
          />
        ) : open ? (
          <div className='flex flex-col gap-2'>
            <div className='flex items-center justify-between'>
              <span className='text-sm text-muted-foreground'>
                能力定义 JSON
              </span>
              <CopyButton
                value={JSON.stringify(item.definition, null, 2)}
                label='能力定义 JSON'
              />
            </div>
            <JsonEditor
              value={JSON.stringify(item.definition, null, 2)}
              readOnly
              size='compact'
              aria-label={`${item.name} 能力定义 JSON`}
            />
          </div>
        ) : null}
      </CollapsibleContent>
      {edit && item.kind !== 'prompts' && (
        <DescriptionDialog
          item={item}
          close={() => setEdit(false)}
          save={(v) => update(item.enabled, v)}
          pending={pending}
        />
      )}
    </Collapsible>
  )
}
function DescriptionDialog({
  item,
  close,
  save,
  pending,
}: {
  item: Capability
  close: () => void
  save: (v: string) => Promise<void>
  pending: boolean
}) {
  const restoreFocus = useReturnFocus()
  const form = useForm({
    resolver: zodResolver(z.object({ description: z.string().max(10000) })),
    defaultValues: { description: item.description },
  })
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !pending) close()
      }}
    >
      <DialogContent onCloseAutoFocus={restoreFocus}>
        <DialogHeader>
          <DialogTitle>编辑能力说明</DialogTitle>
          <DialogDescription>{item.name}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit((v) => save(v.description))}
          >
            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>说明</FormLabel>
                  <FormControl>
                    <Textarea {...field} rows={6} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type='button' variant='outline' onClick={close}>
                取消
              </Button>
              <Button disabled={pending}>保存</Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
export function RunPanel({
  item,
  service,
  close,
  onBusyChange,
}: {
  item: Capability
  service: Service
  close: () => void
  onBusyChange?: (busy: boolean) => void
}) {
  const { write } = useMcp()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<Schema['McpResult'] | null>(null)
  const args = (item.definition.arguments ?? []) as {
    name: string
    description?: string
    required?: boolean
  }[]
  const inputSchema: InputSchema =
    item.kind === 'prompts'
      ? {
          type: 'object',
          properties: Object.fromEntries(
            args.map((a) => [
              a.name,
              { type: 'string', description: a.description },
            ])
          ),
          required: args.filter((a) => a.required).map((a) => a.name),
        }
      : ((item.definition.inputSchema ?? {
          type: 'object',
          properties: {},
        }) as InputSchema)
  const canForm = supportsForm(inputSchema)
  const [mode, setMode] = useState(canForm ? 'form' : 'json')
  const [resultMode, setResultMode] = useState('content')
  const initial = schemaDefaults(inputSchema) ?? {}
  const form = useForm({
    resolver: zodResolver(z.object({ json: z.string(), uri: z.string() })),
    defaultValues: {
      json: JSON.stringify(initial, null, 2),
      uri: item.kind === 'templates' ? item.key : '',
    },
  })
  return (
    <section
      aria-label={`运行 ${item.name}`}
      className='flex min-w-0 flex-col gap-4'
    >
      <Form {...form}>
        <form
          className='flex flex-col gap-4'
          onSubmit={form.handleSubmit(async (v) => {
            if (pending) return
            setPending(true)
            onBusyChange?.(true)
            form.clearErrors()
            setError(null)
            setResult(null)
            try {
              let argumentsValue = {}
              if (['tools', 'prompts'].includes(item.kind)) {
                argumentsValue = parseArguments(v.json)
                const validation = canForm
                  ? validateRequired(inputSchema, argumentsValue)
                  : null
                if (validation) {
                  form.setError('json', { message: validation })
                  return
                }
              }
              setResult(
                await write<Schema['McpResult']>(
                  `/services/${service.id}/run`,
                  'POST',
                  {
                    kind: item.kind,
                    key: item.key,
                    arguments: argumentsValue,
                    uri: item.kind === 'templates' ? v.uri : null,
                  }
                )
              )
            } catch (e) {
              setError(e)
            } finally {
              setPending(false)
              onBusyChange?.(false)
            }
          })}
        >
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <h3 className='min-w-0 text-base font-medium break-all'>
              {item.kind === 'tools'
                ? '运行工具'
                : '预览' + kindNames[item.kind]}
              ：{item.name}
            </h3>
            {['tools', 'prompts'].includes(item.kind) && (
              <Tabs
                value={mode}
                onValueChange={(v) => {
                  try {
                    const value = parseArguments(form.getValues('json'))
                    if (v === 'form') {
                      const error = validateRequired(
                        inputSchema,
                        value,
                        '',
                        false
                      )
                      if (error) throw Error(error)
                    }
                    form.clearErrors('json')
                    setMode(v)
                  } catch (e) {
                    form.setError('json', {
                      message: e instanceof Error ? e.message : 'JSON 无效',
                    })
                  }
                }}
              >
                <TabsList>
                  <TabsTrigger value='form' disabled={!canForm || pending}>
                    表单
                  </TabsTrigger>
                  <TabsTrigger value='json' disabled={pending}>
                    JSON
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            )}
          </div>
          {['tools', 'prompts'].includes(item.kind) && (
            <>
              {!canForm && (
                <p className='text-sm text-muted-foreground'>
                  此工具包含复杂参数定义，请使用 JSON
                  输入；提交时按完整定义校验。
                </p>
              )}
              <FormField
                control={form.control}
                name='json'
                render={({ field }) => (
                  <FormItem>
                    {mode === 'json' ? (
                      <>
                        <FormLabel>参数（JSON）</FormLabel>
                        <FormControl>
                          <JsonEditor
                            {...field}
                            size='compact'
                            disabled={pending}
                            aria-label='参数（JSON）'
                          />
                        </FormControl>
                      </>
                    ) : Object.keys(inputSchema.properties ?? {}).length ===
                      0 ? (
                      <p className='py-4 text-sm text-muted-foreground'>
                        此工具不需要任何参数。
                      </p>
                    ) : (
                      <SchemaFields
                        schema={inputSchema}
                        value={parseArguments(field.value)}
                        disabled={pending}
                        onChange={(v) =>
                          field.onChange(JSON.stringify(v, null, 2))
                        }
                      />
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
          {item.kind === 'templates' && (
            <FormField
              control={form.control}
              name='uri'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>资源地址（替换模板变量）</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
          {!!error && <RequestError error={error} />}
          <div className='flex justify-end gap-2'>
            <Button
              type='button'
              variant='outline'
              onClick={close}
              disabled={pending}
            >
              取消
            </Button>
            <Button disabled={pending}>
              <Play data-icon='inline-start' />
              {pending
                ? '执行中…'
                : item.kind === 'tools'
                  ? '运行'
                  : '获取内容'}
            </Button>
          </div>
        </form>
      </Form>
      {result && (
        <div
          className='flex min-w-0 flex-col gap-3 rounded-lg border bg-muted/30 p-4'
          aria-live='polite'
        >
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <p className='text-sm'>
              {result.result.isError ? '工具执行失败' : '执行成功'} ·{' '}
              {result.duration_ms} ms
            </p>
            <CopyButton
              value={JSON.stringify(result.result, null, 2)}
              label='运行结果'
            />
          </div>
          <Tabs value={resultMode} onValueChange={setResultMode}>
            <TabsList>
              <TabsTrigger value='content'>内容</TabsTrigger>
              <TabsTrigger value='json'>原始 JSON</TabsTrigger>
            </TabsList>
            <TabsContent value='content'>
              <ResultContent value={result.result} />
            </TabsContent>
            <TabsContent value='json'>
              <JsonEditor
                value={JSON.stringify(result.result, null, 2)}
                readOnly
                size='compact'
                aria-label='运行结果 JSON'
              />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </section>
  )
}

function ResultContent({ value }: { value: Record<string, unknown> }) {
  // Treat upstream output as text only; never render supplied HTML or fetch media.
  const blocks: unknown[] = Array.isArray(value.content)
    ? value.content
    : Array.isArray(value.contents)
      ? value.contents
      : Array.isArray(value.messages)
        ? value.messages.map((message) => message.content)
        : []
  const texts = blocks.flatMap((block) => {
    if (!block || typeof block !== 'object') return []
    const text = 'text' in block ? block.text : null
    return typeof text === 'string' ? [text] : []
  })
  return texts.length ? (
    <pre className='max-h-96 overflow-auto text-sm break-words whitespace-pre-wrap'>
      {texts.join('\n\n')}
    </pre>
  ) : (
    <JsonEditor
      value={JSON.stringify(value.structuredContent ?? value, null, 2)}
      readOnly
      size='compact'
      aria-label='结构化结果'
    />
  )
}
