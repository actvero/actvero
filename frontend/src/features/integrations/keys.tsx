import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { TableCell, TableRow } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  applications,
  timestamp,
  type Application,
  type ApplicationKey,
} from './data'
import { CopyButton, IntegrationTable, NoItems } from './shared'

const keyStatus = { active: '有效', expired: '已到期', revoked: '已撤销' }

export function ApplicationKeys({ app }: { app: Application }) {
  const { organization, csrf } = useOrganization()
  const path = `${applications}/${app.id}/keys`
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<ApplicationKey>()
  const [revoking, setRevoking] = useState(false)
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'integration-keys',
      path,
    ],
    queryFn: ({ signal }) =>
      api<ApplicationKey[]>(path, 'GET', undefined, undefined, signal),
  })

  async function revoke() {
    if (!selected || revoking) return
    setRevoking(true)
    try {
      await api<void>(path + '/' + selected.id, 'DELETE', undefined, csrf)
      void query.refetch()
      setSelected(undefined)
      toast.success('密钥已撤销')
    } catch (error) {
      toast.error(messageOf(error))
    } finally {
      setRevoking(false)
    }
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex justify-end'>
        <Button disabled={!app.enabled} onClick={() => setCreating(true)}>
          <Plus data-icon='inline-start' />
          生成密钥
        </Button>
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : query.data.length ? (
        <IntegrationTable
          headers={['名称', '密钥', '状态', '到期时间', '最近使用', '操作']}
        >
          {query.data.map((key) => (
            <TableRow key={key.id}>
              <TableCell className='font-medium'>{key.name}</TableCell>
              <TableCell className='font-mono text-xs'>{key.hint}</TableCell>
              <TableCell>
                <Badge
                  variant={
                    key.status === 'active' && app.enabled
                      ? 'success'
                      : 'secondary'
                  }
                >
                  {key.status === 'active' && !app.enabled
                    ? '应用已停用'
                    : keyStatus[key.status]}
                </Badge>
              </TableCell>
              <TableCell>{timestamp(key.expires_at)}</TableCell>
              <TableCell>{timestamp(key.last_used_at)}</TableCell>
              <TableCell>
                {key.status === 'active' && (
                  <Button
                    variant='ghost'
                    size='sm'
                    onClick={() => setSelected(key)}
                  >
                    撤销
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </IntegrationTable>
      ) : (
        <NoItems
          title='暂无密钥'
          detail={
            app.enabled
              ? '生成密钥后，将它配置在接入系统的后端。'
              : '启用应用后可以生成密钥。'
          }
        />
      )}
      <ConfirmDialog
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open && !revoking) setSelected(undefined)
        }}
        title='撤销密钥'
        desc={`撤销「${selected?.name ?? ''}」后，通过这把密钥发起的调用将被拒绝。`}
        cancelBtnText='取消'
        confirmText={revoking ? '撤销中…' : '撤销密钥'}
        destructive
        isLoading={revoking}
        handleConfirm={() => void revoke()}
      />
      {creating && (
        <CreateKey
          path={path}
          close={() => setCreating(false)}
          refresh={() => void query.refetch()}
        />
      )}
    </div>
  )
}

function CreateKey({
  path,
  close,
  refresh,
}: {
  path: string
  close: () => void
  refresh: () => void
}) {
  const { csrf } = useOrganization()
  const [name, setName] = useState('')
  const [days, setDays] = useState<30 | 90 | 365>(90)
  const [busy, setBusy] = useState(false)
  const [secret, setSecret] = useState('')
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{secret ? '复制应用密钥' : '生成密钥'}</DialogTitle>
          {secret && (
            <DialogDescription>
              密钥只显示一次。请复制并保存在接入系统的后端。
            </DialogDescription>
          )}
        </DialogHeader>
        {secret ? (
          <>
            <Input
              aria-label='应用密钥'
              className='font-mono'
              value={secret}
              readOnly
            />
            <DialogFooter>
              <CopyButton value={secret} label='复制应用密钥' />
              <Button onClick={close}>完成</Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className='flex flex-col gap-4'
            onSubmit={async (event) => {
              event.preventDefault()
              if (!name.trim() || busy) return
              setBusy(true)
              try {
                const created = await api<Schema['ApplicationKeyCreated']>(
                  path,
                  'POST',
                  { name: name.trim(), days },
                  csrf
                )
                setSecret(created.secret)
                refresh()
              } catch (error) {
                toast.error(messageOf(error))
              } finally {
                setBusy(false)
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor='integration-key-name'>密钥名称</FieldLabel>
                <Input
                  id='integration-key-name'
                  value={name}
                  maxLength={100}
                  placeholder='例如 主服务'
                  required
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor='integration-key-days'>有效期</FieldLabel>
                <Select
                  value={String(days)}
                  onValueChange={(value) =>
                    setDays(value === '30' ? 30 : value === '365' ? 365 : 90)
                  }
                >
                  <SelectTrigger id='integration-key-days'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='30'>30 天</SelectItem>
                      <SelectItem value='90'>90 天</SelectItem>
                      <SelectItem value='365'>365 天</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </FieldGroup>
            <DialogFooter>
              <Button
                variant='outline'
                type='button'
                onClick={close}
                disabled={busy}
              >
                取消
              </Button>
              <Button disabled={busy || !name.trim()}>
                {busy ? '生成中…' : '生成密钥'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
