import { useEffect, useId, useState, type ComponentProps } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SelectionRow } from '@/components/ui/selection-row'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { ListPager } from '@/features/departments/list-pager'
import {
  DepartmentGrantPicker,
  type DepartmentSelection,
} from '@/features/departments/picker'
import { DepartmentScopePreview } from '@/features/departments/scope-preview'

type PickerProps = Omit<ComponentProps<'div'>, 'onChange'> & {
  value: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
  includeAdministrators?: boolean
  selectionLabel?: string
  departmentScope?: DepartmentSelection
}

export function MemberPicker({
  departmentScope,
  value,
  onChange,
  disabled,
  includeAdministrators,
  selectionLabel = '共享给成员',
  className,
  ...props
}: PickerProps) {
  const pickerProps = {
    value,
    onChange,
    disabled,
    includeAdministrators,
    selectionLabel,
  }
  if (!departmentScope)
    return (
      <MemberPickerList {...props} {...pickerProps} className={className} />
    )
  return (
    <div
      {...props}
      role='group'
      aria-label={selectionLabel}
      className={cn('@container min-w-0', className)}
    >
      <div className='grid min-w-0 gap-5 @min-[34rem]:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]'>
        <div className='flex min-w-0 flex-col gap-4'>
          <DepartmentGrantPicker {...departmentScope} disabled={disabled} />
          <MemberGrantPicker {...pickerProps} />
        </div>
        <DepartmentScopePreview
          key={JSON.stringify([value, departmentScope.value])}
          members={value}
          grants={departmentScope.value}
        />
      </div>
    </div>
  )
}

function MemberSelectionDialog({
  value,
  onChange,
  close,
  ...props
}: PickerProps & { close: () => void }) {
  const [draft, setDraft] = useState(value)
  return (
    <>
      <MemberPickerList {...props} value={draft} onChange={setDraft} />
      <DialogFooter>
        <Button type='button' variant='outline' onClick={close}>
          取消
        </Button>
        <Button
          type='button'
          disabled={props.disabled}
          onClick={() => {
            onChange(draft)
            close()
          }}
        >
          应用选择
        </Button>
      </DialogFooter>
    </>
  )
}

function MemberGrantPicker(props: PickerProps) {
  const { value, onChange, disabled, includeAdministrators } = props
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const { organization, user, csrf } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/members/selection`
  // CSRF authenticates this read; cache identity is tenant + user, never a credential.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      path,
      value,
      page,
    ],
    queryFn: ({ signal }) =>
      api<Schema['MemberPage']>(
        path,
        'POST',
        { member_ids: value, page },
        csrf,
        signal
      ),
    enabled: value.length > 0,
  })
  const result = query.data
  function change(ids: string[]) {
    setPage(1)
    onChange(ids)
  }
  return (
    <section className='flex min-w-0 flex-col gap-2' aria-label='单独授权成员'>
      <div className='flex flex-wrap items-center gap-x-2'>
        <h3 className='text-sm font-semibold'>成员</h3>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button type='button' variant='ghost' size='sm' disabled={disabled}>
              <Plus data-icon='inline-start' /> 添加成员
            </Button>
          </DialogTrigger>
          <DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl'>
            <DialogHeader>
              <DialogTitle>选择成员</DialogTitle>
              <DialogDescription>为指定成员单独授权。</DialogDescription>
            </DialogHeader>
            <MemberSelectionDialog
              {...props}
              onChange={change}
              close={() => setOpen(false)}
            />
          </DialogContent>
        </Dialog>
      </div>
      {value.length === 0 ? (
        <p className='text-sm text-muted-foreground'>未单独授权成员</p>
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : !result ? (
        <LoadingState />
      ) : (
        <>
          <ScrollArea
            role='region'
            aria-label='已授权成员'
            viewportClassName='max-h-64'
          >
            <ul className='flex flex-col gap-2'>
              {result.items.map((member) => (
                <li
                  key={member.id}
                  className='flex min-w-0 items-center gap-2 rounded-md border px-3 py-1.5'
                >
                  <UserAvatar user={member} />
                  <div className='min-w-0 flex-1'>
                    <div className='text-sm font-medium break-words'>
                      {member.name}
                    </div>
                    {member.status !== 'active' && (
                      <p className='text-xs text-muted-foreground'>
                        当前不可用
                      </p>
                    )}
                    {!includeAdministrators &&
                      member.status === 'active' &&
                      member.role === 'administrator' && (
                        <p className='text-xs text-muted-foreground'>
                          管理员已有权限
                        </p>
                      )}
                  </div>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-8'
                    aria-label={`移除 ${member.name}`}
                    disabled={disabled}
                    onClick={() =>
                      change(value.filter((id) => id !== member.id))
                    }
                  >
                    <X />
                  </Button>
                </li>
              ))}
            </ul>
          </ScrollArea>
          {result.total < value.length && (
            <p className='text-sm text-muted-foreground'>
              部分成员已不可用，可在添加成员中清空选择。
            </p>
          )}
          <ListPager page={page} total={result.total} onChange={setPage} />
        </>
      )}
    </section>
  )
}

function MemberPickerList({
  value,
  onChange,
  disabled = false,
  includeAdministrators = false,
  selectionLabel = '共享给成员',
  className,
  ...props
}: Omit<PickerProps, 'departmentScope'>) {
  const id = useId()
  const { organization, user, csrf } = useOrganization()
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('all')
  const [page, setPage] = useState(1)
  useEffect(() => {
    if (q === search.trim()) return
    const timer = setTimeout(() => {
      setQ(search.trim())
      setPage(1)
    }, 250)
    return () => clearTimeout(timer)
  }, [search, q])
  const selected = tab === 'selected'
  const path = `/enterprises/${organization.tenant_id}/members`
  // CSRF authenticates this read; cache identity is tenant + user, never a credential.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'member-picker',
      path,
      tab,
      q,
      page,
      selected ? value : null,
      includeAdministrators,
    ],
    queryFn: ({ signal }) =>
      selected
        ? api<Schema['MemberPage']>(
            path + '/selection',
            'POST',
            { member_ids: value, q, page },
            csrf,
            signal
          )
        : api<Schema['MemberPage']>(
            path +
              '?' +
              new URLSearchParams({
                q,
                page: String(page),
                status: 'active',
                ...(includeAdministrators ? {} : { role: 'member' }),
              }),
            'GET',
            undefined,
            undefined,
            signal
          ),
  })
  const data = query.data
  const rows = data?.items ?? []
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / 20))
  useEffect(() => {
    if (data && page > pages) {
      const timer = setTimeout(() => setPage(pages), 0)
      return () => clearTimeout(timer)
    }
  }, [data, page, pages])
  const ready = !!data && !query.isFetching && q === search.trim()
  const eligible = rows.filter(
    (m) =>
      m.status === 'active' && (includeAdministrators || m.role === 'member')
  )
  const additions = eligible
    .filter((m) => !value.includes(m.id))
    .map((m) => m.id)
  function toggle(memberId: string, checked: boolean) {
    onChange(
      checked
        ? [...new Set([...value, memberId])]
        : value.filter((v) => v !== memberId)
    )
  }
  return (
    <Card
      {...props}
      role='group'
      aria-label={selectionLabel}
      density='compact'
      className={cn('overflow-hidden', className)}
    >
      <CardContent tone='muted' className='flex min-w-0 flex-col gap-3 p-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='text-sm' aria-live='polite'>
            已选择 {value.length} 人
          </span>
          <Button
            type='button'
            variant='ghost'
            size='sm'
            disabled={disabled || !value.length}
            onClick={() => onChange([])}
          >
            清空选择
          </Button>
        </div>
        <Input
          aria-label='搜索成员'
          placeholder='搜索姓名或邮箱…'
          maxLength={200}
          value={search}
          disabled={disabled}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <Tabs
            value={tab}
            onValueChange={(v) => {
              setTab(v)
              setPage(1)
            }}
          >
            <TabsList>
              <TabsTrigger value='all' disabled={disabled}>
                全部成员
              </TabsTrigger>
              <TabsTrigger value='selected' disabled={disabled}>
                已选成员
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div className='flex flex-wrap gap-1'>
            <Button
              type='button'
              variant='ghost'
              size='sm'
              disabled={
                disabled ||
                !ready ||
                !additions.length ||
                value.length + additions.length > 1000
              }
              onClick={() => onChange([...value, ...additions])}
            >
              选择本页
            </Button>
            <Button
              type='button'
              variant='ghost'
              size='sm'
              disabled={
                disabled || !ready || !rows.some((m) => value.includes(m.id))
              }
              onClick={() =>
                onChange(value.filter((v) => !rows.some((m) => m.id === v)))
              }
            >
              取消本页选择
            </Button>
          </div>
        </div>
        <Separator />
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError
            error={query.error}
            retry={() => {
              void query.refetch()
            }}
          />
        ) : (
          <ScrollArea
            className='overflow-hidden'
            key={`${tab}-${q}-${page}`}
            viewportClassName='max-h-75'
            aria-label='成员列表'
            role='region'
          >
            {!rows.length && (
              <p className='py-6 text-center text-sm text-muted-foreground'>
                {q
                  ? '没有匹配的成员'
                  : selected
                    ? '尚未选择成员'
                    : '暂无可选成员'}
              </p>
            )}
            {rows.map((m) => {
              const checked = value.includes(m.id)
              const unavailable =
                m.status !== 'active' ||
                (!includeAdministrators && m.role !== 'member')
              return (
                <SelectionRow key={m.id} htmlFor={`${id}-${m.id}`}>
                  <Checkbox
                    id={`${id}-${m.id}`}
                    aria-label={`选择 ${m.name}`}
                    checked={checked}
                    disabled={
                      disabled ||
                      !ready ||
                      (!checked && (unavailable || value.length >= 1000))
                    }
                    onCheckedChange={(v) => toggle(m.id, v === true)}
                  />
                  <UserAvatar user={m} />
                  <span className='flex min-w-0 flex-1 flex-col gap-1'>
                    <span className='break-words'>{m.name}</span>
                    <span className='text-sm break-all text-muted-foreground'>
                      {m.email || '未设置邮箱'}
                      {unavailable &&
                        (m.role === 'administrator' && m.status === 'active'
                          ? ' · 管理员已有权限，可移除此选择'
                          : ' · 已暂停或移出，请移除此选择')}
                    </span>
                  </span>
                </SelectionRow>
              )
            })}
          </ScrollArea>
        )}
        <Separator />
        <div className='flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground'>
          <span>
            {data
              ? `共 ${data.total} 人 · 第 ${page} / ${pages} 页`
              : '每页 20 人'}
          </span>
          <div className='flex gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={disabled || !ready || page <= 1}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={disabled || !ready || page >= pages}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
        <p className='text-sm text-muted-foreground'>
          {includeAdministrators
            ? '最多指定 1000 人，包含管理员。'
            : '最多指定 1000 人；管理员始终有管理权限，无需选择。'}
        </p>
      </CardContent>
    </Card>
  )
}
