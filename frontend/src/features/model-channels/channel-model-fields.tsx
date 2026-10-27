import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { Check, Plus, RefreshCw, X } from 'lucide-react'
import { dateTime } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { modelIds, validModelId, type ChannelValues } from './channel-form'

export function ChannelModelFields({
  modelDiscovery,
  candidates,
  discovered,
  partial,
  fetchedAt,
  pending,
  discovering,
  discover,
}: {
  modelDiscovery: boolean
  candidates: string[]
  discovered: boolean
  partial: boolean
  fetchedAt?: string
  pending: boolean
  discovering: boolean
  discover: () => void
}) {
  const form = useFormContext<ChannelValues>()
  const selected = useWatch({ control: form.control, name: 'models' })
  const [query, setQuery] = useState('')
  const [queryError, setQueryError] = useState('')
  const [batchOpen, setBatchOpen] = useState(false)
  const [visibleCount, setVisibleCount] = useState(100)
  const term = query.trim()
  const choices = [...new Set(candidates)]
  const matches = choices.filter((id) =>
    id.toLowerCase().includes(term.toLowerCase())
  )
  const exactMatch = choices.includes(term)
  const customAvailable = !!term && !exactMatch && !selected.includes(term)

  function change(ids: string[]) {
    form.setValue('models', ids, { shouldDirty: true, shouldValidate: true })
  }
  function add(id: string, clearSearch = true) {
    if (selected.includes(id)) return
    if (!validModelId(id)) {
      setQueryError('模型 ID 最多 200 个字符，支持字母、数字和 . _ : / @ + -')
      return
    }
    if (selected.length >= 1000) {
      setQueryError('每个渠道最多登记 1000 个模型')
      return
    }
    change([...selected, id])
    if (clearSearch) setQuery('')
    setQueryError('')
  }
  async function addBatch() {
    if (!(await form.trigger('manual_models'))) return
    const next = [
      ...new Set([...selected, ...modelIds(form.getValues('manual_models'))]),
    ]
    if (next.length > 1000) {
      form.setError('manual_models', {
        message: '每个渠道最多登记 1000 个模型',
      })
      return
    }
    change(next)
    form.setValue('manual_models', '')
    setBatchOpen(false)
  }

  return (
    <Card className='min-w-0'>
      <CardHeader>
        <CardTitle>选择上游模型</CardTitle>
      </CardHeader>
      <CardContent className='flex min-w-0 flex-col gap-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <p role='status' className='text-sm text-muted-foreground'>
            {discovering
              ? '正在获取上游列表…'
              : discovered
                ? `上游返回 ${candidates.length} 个模型 · 已选 ${selected.length} 个`
                : `已选 ${selected.length} 个模型`}
          </p>
          {modelDiscovery && (
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={pending || discovering}
              onClick={discover}
            >
              <RefreshCw className={discovering ? 'animate-spin' : ''} />
              {discovered ? '重新获取' : '从上游获取'}
            </Button>
          )}
        </div>
        {fetchedAt && (
          <p className='text-xs text-muted-foreground'>
            更新于 {dateTime(fetchedAt)}
          </p>
        )}
        {!modelDiscovery && (
          <Alert>
            <AlertTitle>需要提供模型 ID</AlertTitle>
            <AlertDescription>请手动填写模型 ID。</AlertDescription>
          </Alert>
        )}
        <FormField
          control={form.control}
          name='models'
          render={() => (
            <FormItem>
              <FormLabel>搜索或输入模型 ID</FormLabel>
              <FormControl>
                <Input
                  aria-label='搜索或输入模型 ID'
                  placeholder='输入上游模型 ID'
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value)
                    setVisibleCount(100)
                    setQueryError('')
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      if (exactMatch || customAvailable) add(term)
                    }
                  }}
                  aria-invalid={!!queryError}
                  aria-describedby={
                    queryError ? 'channel-model-query-error' : undefined
                  }
                  disabled={pending}
                />
              </FormControl>
              {queryError && (
                <p
                  id='channel-model-query-error'
                  role='alert'
                  className='text-sm text-destructive'
                >
                  {queryError}
                </p>
              )}
              {(choices.length > 0 || term) && (
                <div
                  role='group'
                  aria-label='模型搜索结果'
                  className='flex max-h-80 flex-col overflow-y-auto rounded-md border p-1'
                >
                  {!!matches.length && (
                    <div className='flex items-center justify-between gap-2 border-b p-2'>
                      <span className='text-xs text-muted-foreground'>
                        匹配 {matches.length} 个
                      </span>
                      <Button
                        type='button'
                        variant='ghost'
                        size='sm'
                        disabled={pending}
                        onClick={() => {
                          const next = [...new Set([...selected, ...matches])]
                          if (next.length > 1000)
                            setQueryError(
                              '每个渠道最多登记 1000 个模型，请缩小搜索范围'
                            )
                          else change(next)
                        }}
                      >
                        全选匹配结果
                      </Button>
                    </div>
                  )}
                  {matches.slice(0, visibleCount).map((id) => (
                    <Button
                      key={id}
                      type='button'
                      variant='ghost'
                      className='h-auto min-h-9 min-w-0 justify-start text-left font-mono break-all whitespace-normal'
                      disabled={pending}
                      aria-pressed={selected.includes(id)}
                      onClick={() =>
                        selected.includes(id)
                          ? change(selected.filter((item) => item !== id))
                          : add(id, false)
                      }
                    >
                      <span className='flex size-4 shrink-0 items-center justify-center rounded-sm border'>
                        {selected.includes(id) && <Check className='size-3' />}
                      </span>
                      {id}
                    </Button>
                  ))}
                  {matches.length > visibleCount && (
                    <Button
                      type='button'
                      variant='ghost'
                      onClick={() => setVisibleCount((count) => count + 100)}
                    >
                      显示更多模型
                    </Button>
                  )}
                  {customAvailable && (
                    <Button
                      type='button'
                      variant='ghost'
                      className='h-auto min-h-9 min-w-0 justify-start text-left break-all whitespace-normal'
                      disabled={pending}
                      onClick={() => add(term)}
                    >
                      <Plus /> 添加自定义模型 ID：{term}
                    </Button>
                  )}
                  {!matches.length && !customAvailable && (
                    <p
                      role='status'
                      className='p-2 text-sm text-muted-foreground'
                    >
                      {selected.includes(term)
                        ? '已在清单中'
                        : '没有可选的匹配模型'}
                    </p>
                  )}
                </div>
              )}
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='flex flex-col gap-2'>
          <p className='text-sm font-medium'>已选择（{selected.length}）</p>
          {selected.length ? (
            <div
              role='group'
              aria-label='已选模型'
              className='flex max-h-40 flex-wrap gap-2 overflow-y-auto'
            >
              {selected.map((id) => (
                <Badge
                  key={id}
                  variant='secondary'
                  className='max-w-full gap-1 font-mono'
                >
                  <span className='min-w-0 break-all'>{id}</span>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-6 shrink-0'
                    aria-label={`移除 ${id}`}
                    disabled={pending}
                    onClick={() =>
                      change(selected.filter((value) => value !== id))
                    }
                  >
                    <X />
                  </Button>
                </Badge>
              ))}
            </div>
          ) : (
            <p className='text-sm text-muted-foreground'>尚未选择模型</p>
          )}
        </div>
        {partial && (
          <Alert>
            <AlertTitle>上游只返回了部分目录</AlertTitle>
            <AlertDescription>
              可从当前结果选择，也可输入其他实际模型 ID。
            </AlertDescription>
          </Alert>
        )}
        {discovered && !candidates.length && (
          <p className='text-sm text-muted-foreground'>
            上游返回了空目录，可继续输入实际模型 ID。
          </p>
        )}
        <div className='flex flex-wrap items-center gap-2'>
          <CollapsibleSection
            title='批量粘贴模型 ID'
            open={batchOpen || !!form.formState.errors.manual_models}
            onOpenChange={setBatchOpen}
          >
            <div className='flex flex-col gap-2'>
              <FormField
                control={form.control}
                name='manual_models'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>模型 ID</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        rows={3}
                        disabled={pending}
                        placeholder={'model-id\n另一个-model-id'}
                      />
                    </FormControl>
                    <FormDescription>
                      每行一个，或用逗号分隔；重复项会合并。
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button
                type='button'
                variant='outline'
                size='sm'
                className='self-end'
                disabled={pending}
                onClick={() => void addBatch()}
              >
                <Plus />
                加入清单
              </Button>
            </div>
          </CollapsibleSection>
        </div>
      </CardContent>
    </Card>
  )
}
