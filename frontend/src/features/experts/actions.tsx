import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Ellipsis, EyeOff, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { RequestError } from '@/components/request-state'
import { useExperts, type Expert, type ExpertSummary } from './shared'

export function ExpertActions({
  expert,
  edit = false,
  disabled = false,
  changed,
  deleted,
}: {
  expert: ExpertSummary
  edit?: boolean
  disabled?: boolean
  changed?: (expert: Expert) => void
  deleted?: () => void | Promise<void>
}) {
  const { key, csrf, refresh } = useExperts()
  const client = useQueryClient()
  const [selection, setSelection] = useState<{
    action: 'delete' | 'withdraw'
    expert: ExpertSummary
  }>()
  const action = selection?.action
  const target = selection?.expert ?? expert
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>()
  function choose(next: 'delete' | 'withdraw') {
    setError(undefined)
    setSelection({ action: next, expert })
  }
  return (
    <div onClick={(event) => event.stopPropagation()}>
      <div className='flex items-center justify-end gap-1'>
        {edit && (
          <Button variant='ghost' size='sm' asChild>
            <Link
              to='/experts/$expertId'
              params={{ expertId: expert.id }}
              aria-label={`编辑专家 ${expert.name}`}
            >
              编辑
            </Link>
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type='button'
              variant='ghost'
              size='icon'
              disabled={disabled || pending}
              aria-label={`更多专家操作 ${expert.name}`}
            >
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end'>
            <DropdownMenuGroup>
              {expert.current_release && (
                <>
                  <DropdownMenuItem onSelect={() => choose('withdraw')}>
                    <EyeOff />
                    下架专家
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem
                variant='destructive'
                onSelect={() => choose('delete')}
              >
                <Trash2 />
                删除专家
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {action && (
        <ConfirmDialog
          open
          title={
            action === 'delete'
              ? `删除专家“${target.name}”`
              : `下架专家“${target.name}”`
          }
          desc={
            action === 'delete'
              ? `将永久删除草稿和全部发布版本，无法撤销。${target.current_release ? '专家将立即不可用，已有会话的后续受控调用也会停止。' : ''}关联的技能和连接器会保留。`
              : '下架后成员无法使用这位专家，已有会话的后续受控调用也会停止。草稿和版本记录会保留。'
          }
          destructive={action === 'delete'}
          confirmText={
            pending ? '处理中…' : action === 'delete' ? '删除专家' : '确认下架'
          }
          cancelBtnText='取消'
          isLoading={pending}
          onOpenChange={(open) => {
            if (!open && !pending) setSelection(undefined)
          }}
          handleConfirm={async () => {
            if (pending) return
            setPending(true)
            setError(undefined)
            try {
              if (action === 'delete') {
                await api(
                  `/experts/${target.id}`,
                  'DELETE',
                  { revision: target.revision },
                  csrf
                )
                client.removeQueries({
                  queryKey: [...key, 'detail', target.id],
                  exact: true,
                })
                await deleted?.()
                toast.success('专家已删除')
              } else {
                const result = await api<Expert>(
                  `/experts/${target.id}/withdraw`,
                  'POST',
                  { revision: target.revision },
                  csrf
                )
                changed?.(result)
                toast.success('专家已下架')
              }
              setSelection(undefined)
              await refresh()
            } catch (e) {
              setError(e)
            } finally {
              setPending(false)
            }
          }}
        >
          {!!error && <RequestError error={error} />}
        </ConfirmDialog>
      )}
    </div>
  )
}
