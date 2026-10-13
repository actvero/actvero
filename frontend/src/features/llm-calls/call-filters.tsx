import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
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
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { timezones } from '@/features/quota-policies/policy-form'
import { DictionaryPicker } from './dictionary-picker'
import {
  civilAt,
  filterSchema,
  operations,
  results,
  settlements,
  sources,
  zonedMinuteToIso,
  type Filters,
} from './filters'
import { searchToFilters, type CallSearch } from './search'

function SelectField({
  label,
  value,
  onChange,
  items,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  items: Record<string, string>
}) {
  return (
    <div className='flex min-w-0 flex-col gap-2'>
      <span className='text-sm font-medium'>{label}</span>
      <Select
        value={value || 'all'}
        onValueChange={(next) => onChange(next === 'all' ? '' : next)}
      >
        <SelectTrigger aria-label={label} className='w-full'>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value='all'>全部{label}</SelectItem>
            {Object.entries(items).map(([key, text]) => (
              <SelectItem key={key} value={key}>
                {text}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  )
}

function FilterForm({
  search,
  summary,
  onApply,
  compact,
}: {
  search: CallSearch
  summary: boolean
  onApply: (values: Filters) => void
  compact?: boolean
}) {
  const form = useForm<Filters>({
    resolver: zodResolver(filterSchema(summary)),
    defaultValues: searchToFilters(search, summary),
  })
  const values = useWatch({ control: form.control })
  const from = values.fromLocal
    ? zonedMinuteToIso(values.fromLocal, values.timezone ?? 'UTC')
    : null
  const to = values.toLocal
    ? zonedMinuteToIso(values.toLocal, values.timezone ?? 'UTC')
    : null
  return (
    <Form {...form}>
      <form
        className='flex min-w-0 flex-col gap-4'
        onSubmit={(event) => void form.handleSubmit(onApply)(event)}
      >
        {summary && (
          <div className='flex flex-wrap gap-2'>
            {[1, 7, 30].map((days) => (
              <Button
                key={days}
                type='button'
                variant='outline'
                size='sm'
                onClick={() => {
                  const end = Date.now()
                  form.setValue(
                    'fromLocal',
                    civilAt(end - days * 86400000, values.timezone || 'UTC')
                  )
                  form.setValue(
                    'toLocal',
                    civilAt(end, values.timezone || 'UTC')
                  )
                }}
              >
                {days === 1 ? '近24小时' : `近${days}天`}
              </Button>
            ))}
          </div>
        )}
        {search.held && !summary && (
          <Badge variant='outline' className='self-start'>
            只看当前占用 · 日期和结果筛选不适用
          </Badge>
        )}
        <div
          className={
            compact
              ? 'grid min-w-0 gap-4'
              : 'grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4'
          }
        >
          <FormField
            control={form.control}
            name='fromLocal'
            render={({ field }) => (
              <FormItem>
                <FormLabel>开始时间{summary ? ' *' : ''}</FormLabel>
                <FormControl>
                  <Input
                    type='datetime-local'
                    {...field}
                    disabled={values.held}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='toLocal'
            render={({ field }) => (
              <FormItem>
                <FormLabel>结束时间（不包含）{summary ? ' *' : ''}</FormLabel>
                <FormControl>
                  <Input
                    type='datetime-local'
                    {...field}
                    disabled={values.held}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='timezone'
            render={({ field }) => (
              <FormItem>
                <FormLabel>时区</FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      {timezones.map((zone) => (
                        <SelectItem key={zone} value={zone}>
                          {zone}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='source'
            render={({ field }) => (
              <FormItem>
                <FormLabel>来源</FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      {Object.entries(sources)
                        .filter(([key]) => !summary || key !== 'all')
                        .map(([key, text]) => (
                          <SelectItem key={key} value={key}>
                            {text}
                          </SelectItem>
                        ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='member_id'
            render={({ field }) => (
              <FormItem>
                <FormLabel>成员</FormLabel>
                <DictionaryPicker
                  kind='member'
                  value={field.value}
                  onChange={field.onChange}
                />
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='model_id'
            render={({ field }) => (
              <FormItem>
                <FormLabel>模型</FormLabel>
                <DictionaryPicker
                  kind='model'
                  value={field.value}
                  onChange={field.onChange}
                />
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='operation'
            render={({ field }) => (
              <SelectField
                label='操作'
                value={field.value}
                onChange={field.onChange}
                items={operations}
              />
            )}
          />
          {!values.held && (
            <FormField
              control={form.control}
              name='result_status'
              render={({ field }) => (
                <SelectField
                  label='结果状态'
                  value={field.value}
                  onChange={field.onChange}
                  items={results}
                />
              )}
            />
          )}
          {!values.held && (
            <FormField
              control={form.control}
              name='settlement_status'
              render={({ field }) => (
                <SelectField
                  label='结算状态'
                  value={field.value}
                  onChange={field.onChange}
                  items={settlements}
                />
              )}
            />
          )}
          {!summary && !values.held && (
            <FormField
              control={form.control}
              name='call_id'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>调用编号</FormLabel>
                  <FormControl>
                    <Input placeholder='完整 UUID' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </div>
        {!values.held && (
          <FormField
            control={form.control}
            name='channel_id'
            render={({ field }) => (
              <FormItem>
                <FormLabel>最终渠道</FormLabel>
                <FormControl>
                  <DictionaryPicker
                    kind='channel'
                    value={field.value || ''}
                    onChange={(id) => {
                      field.onChange(id)
                      form.setValue('unknown_channel', false)
                    }}
                  />
                </FormControl>
                <FormMessage />
                {values.unknown_channel && (
                  <p className='text-sm text-muted-foreground'>
                    仅未确定渠道{' '}
                    <Button
                      type='button'
                      variant='link'
                      size='sm'
                      onClick={() => form.setValue('unknown_channel', false)}
                    >
                      清除
                    </Button>
                  </p>
                )}
              </FormItem>
            )}
          />
        )}
        {!values.held && (
          <p className='text-xs text-muted-foreground'>
            {values.fromLocal && values.toLocal
              ? `所选时区的本地时间对应 UTC [${from ?? '无效'}，${to ?? '无效'})；切换时区会改变绝对查询范围。`
              : '日期留空时查看所有历史调用。'}
            未配置组织默认时区时明确使用 UTC。
          </p>
        )}
        <div className='flex flex-wrap justify-end gap-2'>
          <Button
            type='button'
            variant='outline'
            onClick={() =>
              form.reset(
                searchToFilters(
                  {
                    ...search,
                    channel_id: '',
                    unknown_channel: false,
                    from: '',
                    to: '',
                    member_id: '',
                    model_id: '',
                    operation: '',
                    source: 'member',
                    result_status: '',
                    settlement_status: '',
                    call_id: '',
                    held: false,
                    page: 1,
                  },
                  summary
                )
              )
            }
          >
            重置
          </Button>
          <Button type='submit'>应用筛选</Button>
        </div>
      </form>
    </Form>
  )
}

export function CallFilters({
  search,
  summary = false,
  compact = false,
  onApply,
}: {
  search: CallSearch
  summary?: boolean
  compact?: boolean
  onApply: (values: Filters) => void
}) {
  const [open, setOpen] = useState(false)
  const count = [
    search.member_id,
    search.model_id,
    search.operation,
    search.result_status,
    search.settlement_status,
    search.call_id,
    search.channel_id,
    search.unknown_channel ? 'unknown_channel' : '',
    search.held ? 'held' : '',
  ].filter(Boolean).length
  const formKey = JSON.stringify(search)
  return (
    <>
      <div
        className={
          compact
            ? 'flex items-center gap-2'
            : 'flex items-center gap-2 md:hidden'
        }
      >
        <Button type='button' variant='outline' onClick={() => setOpen(true)}>
          {summary ? '筛选' : '筛选调用'}
          {count ? ` · ${count} 项` : ''}
        </Button>
        {search.held && <Badge variant='outline'>当前占用</Badge>}
      </div>
      <div className={compact ? 'hidden' : 'hidden md:block'}>
        <FilterForm
          key={formKey}
          search={search}
          summary={summary}
          onApply={onApply}
        />
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          className='w-full sm:max-w-md'
          aria-describedby={undefined}
        >
          <SheetHeader>
            <SheetTitle>{summary ? '筛选用量统计' : '筛选调用'}</SheetTitle>
          </SheetHeader>
          <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-4'>
            {open && (
              <FilterForm
                key={formKey}
                search={search}
                summary={summary}
                compact
                onApply={(values) => {
                  onApply(values)
                  setOpen(false)
                }}
              />
            )}
          </div>
          <SheetFooter className='border-t'>
            <Button
              type='button'
              variant='outline'
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <p className='text-xs text-muted-foreground'>
              应用后以开始时间包含、结束时间不包含的范围查询。
            </p>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  )
}
