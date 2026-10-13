import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ModelCard } from './model-card'
import { ModelExample } from './model-example'
import {
  memberOperations,
  readMyModelSearch,
  type MyModelSearch,
} from './search'

type Model = Schema['MemberModelView']
type Operation = Schema['MemberOperationView']
const searchSchema = z.object({
  q: z.string().trim().max(80, '搜索词最多 80 字'),
  operation: z.enum(['', ...Object.keys(memberOperations)]),
})
type SearchValues = z.infer<typeof searchSchema>

function SearchForm({
  search,
  apply,
}: {
  search: MyModelSearch
  apply: (values: SearchValues) => void
}) {
  const form = useForm<SearchValues>({
    resolver: zodResolver(searchSchema),
    defaultValues: { q: search.q, operation: search.operation },
  })
  return (
    <Form {...form}>
      <form
        className='grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-end'
        onSubmit={(event) => void form.handleSubmit(apply)(event)}
      >
        <FormField
          control={form.control}
          name='q'
          render={({ field }) => (
            <FormItem>
              <FormLabel>搜索模型名称或公开 ID</FormLabel>
              <FormControl>
                <Input placeholder='输入模型名称' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='operation'
          render={({ field }) => (
            <FormItem>
              <FormLabel>操作</FormLabel>
              <Select
                value={field.value || 'all'}
                onValueChange={(value) =>
                  field.onChange(value === 'all' ? '' : value)
                }
              >
                <FormControl>
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value='all'>全部操作</SelectItem>
                    {Object.entries(memberOperations).map(([key, label]) => (
                      <SelectItem key={key} value={key}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button type='submit'>应用筛选</Button>
      </form>
    </Form>
  )
}

function quotaNotice(quota: Schema['QuotaView'] | undefined) {
  if (!quota) return '额度状态暂不可确认；正式请求仍由服务端受理时检查。'
  if (quota.status === 'unconfigured')
    return '尚未配置成员额度策略，暂不可发送请求；请联系管理员。'
  if (quota.windows.some((window) => Number(window.remaining) <= 0))
    return '当前至少一个额度窗口没有剩余积分，等待恢复或联系管理员。'
  return '模型目录只证明当前成员授权与路由可见；实际请求还需个人密钥范围和足够的预占额度。'
}

export function MyModelsPage({ search }: { search: MyModelSearch }) {
  const { organization, user } = useOrganization()
  const navigate = useNavigate()
  const [selection, setSelection] = useState<{
    modelId: string
    kind: Operation['kind']
  } | null>(null)
  const [opening, setOpening] = useState(false)
  const trigger = useRef<HTMLElement | null>(null)
  const params = new URLSearchParams({ page: String(search.page) })
  if (search.q) params.set('q', search.q)
  if (search.operation) params.set('operation', search.operation)
  const scope = ['organization', organization.tenant_id, user.id, 'my-models']
  const models = useQuery({
    queryKey: [...scope, params.toString()],
    queryFn: ({ signal }) =>
      api<Schema['MemberModelPage']>(
        `/account/llm/models?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
    refetchOnWindowFocus: 'always',
  })
  const quota = useQuery({
    queryKey: [...scope, 'quota'],
    queryFn: ({ signal }) =>
      api<Schema['QuotaView']>(
        '/account/llm/quota',
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
    refetchOnWindowFocus: 'always',
  })
  const accessLost =
    (models.error instanceof ApiError &&
      [401, 403].includes(models.error.status)) ||
    (quota.error instanceof ApiError && [401, 403].includes(quota.error.status))
  // A selection is valid only while it exists in the latest authorized page.
  const selectedModel =
    !accessLost && models.isSuccess
      ? models.data.items.find((item) => item.id === selection?.modelId)
      : undefined
  const selectedOperation = selectedModel?.operations.find(
    (item) => item.kind === selection?.kind
  )

  async function openExample(
    model: Model,
    operation: Operation,
    element: HTMLElement
  ) {
    if (opening || accessLost) return
    setOpening(true)
    try {
      const latest = await models.refetch()
      const current = latest.data?.items.find((item) => item.id === model.id)
      if (
        latest.isError ||
        !current?.operations.some((item) => item.kind === operation.kind)
      ) {
        toast.error('模型可用性已变化，请刷新后重新选择')
        return
      }
      trigger.current = element
      setSelection({ modelId: model.id, kind: operation.kind })
    } finally {
      setOpening(false)
    }
  }

  return (
    <PageShell
      title='可用模型'
      description='仅展示当前账号获授权且有可用路由的操作；调用时仍检查密钥范围和额度。'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button asChild variant='outline'>
            <Link to='/my-usage'>我的额度</Link>
          </Button>
          <Button asChild variant='outline'>
            <Link to='/my-access-keys'>访问密钥</Link>
          </Button>
          <Button
            type='button'
            variant='outline'
            disabled={models.isFetching || quota.isFetching}
            onClick={() => {
              setSelection(null)
              void models.refetch()
              void quota.refetch()
            }}
          >
            <RefreshCw />
            刷新
          </Button>
        </div>
      }
    >
      <SearchForm
        key={`${search.q}|${search.operation}`}
        search={search}
        apply={(values) =>
          void navigate({
            to: '/my-models',
            search: readMyModelSearch({ ...values, page: 1 }),
          })
        }
      />
      {accessLost ? (
        <RequestError error={models.error ?? quota.error} />
      ) : models.isPending ? (
        <LoadingState />
      ) : models.isError ? (
        <RequestError
          error={models.error}
          retry={() => void models.refetch()}
        />
      ) : (
        <>
          <Alert>
            <AlertTitle>调用前检查</AlertTitle>
            <AlertDescription>
              {quota.isError
                ? '额度读取失败；请重试确认额度。'
                : quotaNotice(quota.data)}{' '}
              <Link to='/my-usage' className='underline underline-offset-4'>
                查看我的额度
              </Link>
            </AlertDescription>
          </Alert>
          {!models.data.items.length ? (
            <Alert>
              <AlertTitle>
                {search.q || search.operation
                  ? '没有匹配的模型'
                  : '暂无可用模型'}
              </AlertTitle>
              <AlertDescription>
                {search.q || search.operation
                  ? '调整搜索词或操作后重试。'
                  : '当前账号尚无可执行的模型操作，请联系管理员确认授权与路由。'}
              </AlertDescription>
            </Alert>
          ) : (
            <div className='grid min-w-0 gap-4 xl:grid-cols-2'>
              {models.data.items.map((model) => (
                <ModelCard
                  key={model.id}
                  model={model}
                  search={search}
                  onExample={(item, operation, element) =>
                    void openExample(item, operation, element)
                  }
                />
              ))}
            </div>
          )}
          <div className='flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground'>
            <span>
              共 {models.data.total} 个模型 · 第 {models.data.page} 页
            </span>
            <div className='flex gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={search.page <= 1}
                onClick={() =>
                  void navigate({
                    to: '/my-models',
                    search: { ...search, page: search.page - 1 },
                  })
                }
              >
                上一页
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={!models.data.has_more}
                onClick={() =>
                  void navigate({
                    to: '/my-models',
                    search: { ...search, page: search.page + 1 },
                  })
                }
              >
                下一页
              </Button>
            </div>
          </div>
        </>
      )}
      {selectedModel && selectedOperation && (
        <ModelExample
          model={selectedModel}
          operation={selectedOperation}
          close={() => setSelection(null)}
          restoreFocus={() =>
            trigger.current?.isConnected && trigger.current.focus()
          }
        />
      )}
    </PageShell>
  )
}
