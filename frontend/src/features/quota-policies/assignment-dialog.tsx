import { useDeferredValue, useId, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { SelectionRow } from '@/components/ui/selection-row'
import { ServerTable } from '@/components/data-table/server-table'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { ruleLabel } from './policy-form'

type Member = Schema['MemberQuotaMatch']

export function AssignmentButton({ member }: { member: Member }) {
  const [editing, setEditing] = useState<Member | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <Button
        ref={trigger}
        variant='outline'
        size='sm'
        onClick={() => setEditing(member)}
      >
        分配策略
      </Button>
      {editing && (
        <AssignmentDialog
          member={editing}
          close={() => setEditing(null)}
          restoreFocus={() => trigger.current?.focus()}
        />
      )}
    </>
  )
}

function AssignmentDialog({
  member,
  close,
  restoreFocus,
}: {
  member: Member
  close: () => void
  restoreFocus: () => void
}) {
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const id = useId()
  const [selected, setSelected] = useState(member.assigned?.id ?? 'inherit')
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search)
  const [page, setPage] = useState(1)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>()
  const params = new URLSearchParams({
    q,
    page: String(page),
    assignable_only: 'true',
  }).toString()
  const prefix = ['organization', organization.tenant_id, 'quota']
  const query = useQuery({
    queryKey: [...prefix, 'assignment-options', params],
    queryFn: ({ signal }) =>
      api<Schema['QuotaPolicyPage']>(
        '/quota/policies?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  async function save() {
    setPending(true)
    setError(undefined)
    try {
      await api(
        `/quota/members/${member.member_id}/assignment`,
        'PUT',
        {
          policy_id: selected === 'inherit' ? null : selected,
          version: member.assignment_version,
        },
        csrf
      )
      await client.invalidateQueries({ queryKey: prefix })
      toast.success('成员额度策略已更新')
      close()
    } catch (failure) {
      setError(failure)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) close()
      }}
    >
      <DialogContent
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocus()
        }}
      >
        <DialogHeader>
          <DialogTitle>分配额度策略</DialogTitle>
          <DialogDescription>
            一个成员使用一套策略；未指定时继承组织默认策略。
          </DialogDescription>
        </DialogHeader>
        <div className='flex items-center gap-3'>
          <UserAvatar user={member} />
          <span>{member.name}</span>
        </div>
        {member.status === 'paused' && (
          <p className='text-sm text-muted-foreground'>
            成员已暂停，当前无法调用。可以解除指定策略，恢复后再重新分配。
          </p>
        )}
        <RadioGroup
          aria-label='额度策略'
          value={selected}
          onValueChange={setSelected}
          disabled={pending}
        >
          <SelectionRow htmlFor={`${id}-inherit`}>
            <RadioGroupItem id={`${id}-inherit`} value='inherit' />
            继承组织默认策略
          </SelectionRow>
          <Input
            aria-label='搜索额度策略'
            placeholder='搜索策略名称…'
            value={search}
            disabled={pending}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
          />
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            <ServerTable
              items={query.data.items}
              columns={[]}
              total={query.data.total}
              page={page}
              onPage={setPage}
              empty='没有匹配的策略'
              renderItems={(items) => items.length === 0 ? (
                <p className='py-6 text-center text-sm text-muted-foreground'>
                  没有可分配的策略，请先新建策略。
                </p>
              ) : (
                <div className='flex max-h-72 flex-col gap-1 overflow-y-auto'>
                  {items
                    .filter((policy) => !policy.is_default)
                    .map((policy) => (
                      <SelectionRow
                        key={policy.id}
                        htmlFor={`${id}-${policy.id}`}
                      >
                        <RadioGroupItem
                          id={`${id}-${policy.id}`}
                          value={policy.id}
                          disabled={member.status === 'paused'}
                        />
                        <span className='flex min-w-0 flex-col gap-1'>
                          <span>{policy.name}</span>
                          <span className='text-sm text-muted-foreground'>
                            {policy.mode === 'unlimited'
                              ? '不限额度 · 正常记录用量'
                              : policy.rules.map(ruleLabel).join('；')}
                          </span>
                        </span>
                      </SelectionRow>
                    ))}
                </div>
              )}
            />
          )}
        </RadioGroup>
        {!!error && <RequestError error={error} />}
        <DialogFooter>
          <Button variant='outline' onClick={close} disabled={pending}>
            取消
          </Button>
          <Button
            onClick={() => void save()}
            disabled={
              pending ||
              query.isPending ||
              query.isError ||
              (member.status === 'paused' && selected !== 'inherit')
            }
          >
            {pending ? '保存中…' : '保存分配'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
