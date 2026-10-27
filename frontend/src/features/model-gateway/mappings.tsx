import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FieldGroup } from '@/components/ui/field'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  channelTypeName,
  gateway,
  useGateway,
  useGatewayRefresh,
  type Mapping,
} from './api'
import { TextField } from './shared'

export function ModelMappings({ model }: { model: string }) {
  const query = useGateway<Mapping[]>(
    '/mappings?model_name=' + encodeURIComponent(model)
  )
  const [selected, setSelected] = useState<Mapping | null>(null)
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <div className='flex flex-col gap-4 pt-4'>
      <div className='rounded-md bg-muted/50 p-4 text-sm'>
        调用 <span className='font-mono font-medium'>{model}</span>{' '}
        时，优先使用优先级最高的可用渠道；同优先级按权重分配。
      </div>
      <div className='overflow-hidden rounded-md border'>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>渠道</TableHead>
              <TableHead>上游模型 ID</TableHead>
              <TableHead>分组</TableHead>
              <TableHead>优先级 / 权重</TableHead>
              <TableHead>关联</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.map((row) => (
              <TableRow key={row.channel.id}>
                <TableCell>
                  <p className='font-medium'>{row.channel.name}</p>
                  <p className='text-xs text-muted-foreground'>
                    {channelTypeName(row.channel.type)} ·{' '}
                    {row.channel.status === 1 ? '已启用' : '已停用'}
                  </p>
                </TableCell>
                <TableCell className='max-w-72 truncate font-mono text-xs'>
                  {row.associated ? row.upstream_id : '—'}
                </TableCell>
                <TableCell>{row.channel.group}</TableCell>
                <TableCell>
                  {row.channel.priority ?? 0} / {row.channel.weight}
                </TableCell>
                <TableCell>
                  <Button
                    variant={row.associated ? 'outline' : 'secondary'}
                    size='sm'
                    onClick={() => setSelected(row)}
                  >
                    {row.associated ? '编辑映射' : '关联渠道'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!query.data.length && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className='h-28 text-center text-muted-foreground'
                >
                  还没有渠道，请先在渠道页面添加供应商连接。
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {selected && (
        <MappingForm
          key={selected.channel.id + selected.channel.revision}
          row={selected}
          model={model}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
function MappingForm({
  row,
  model,
  onClose,
}: {
  row: Mapping
  model: string
  onClose: () => void
}) {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const [upstream, setUpstream] = useState(row.upstream_id)
  const mutation = useMutation({
    mutationFn: (remove: boolean) =>
      gateway(
        '/mappings',
        'PUT',
        {
          channel_id: row.channel.id,
          model_name: model,
          upstream_id: upstream.trim(),
          revision: row.channel.revision,
          remove,
        },
        csrf
      ),
    onSuccess: async () => {
      await refresh()
      toast.success('渠道映射已保存')
      onClose()
    },
  })
  return (
    <form
      className='flex flex-col gap-4 rounded-md border p-4'
      onSubmit={(e) => {
        e.preventDefault()
        mutation.mutate(false)
      }}
    >
      <div className='flex items-center gap-2'>
        <span className='font-medium'>{row.channel.name}</span>
        <Badge variant='outline'>
          {row.associated ? '编辑映射' : '新增关联'}
        </Badge>
      </div>
      <FieldGroup>
        <TextField
          label='上游模型 ID'
          value={upstream}
          onChange={(e) => setUpstream(e.target.value)}
          required
          hint={`客户端使用 ${model}，此渠道实际请求此处填写的模型 ID。`}
        />
      </FieldGroup>
      {mutation.error && <RequestError error={mutation.error} />}
      <div className='flex justify-between gap-2'>
        <div>
          {row.associated && (
            <Button
              type='button'
              variant='outline'
              disabled={mutation.isPending}
              onClick={() => mutation.mutate(true)}
            >
              移除此关联
            </Button>
          )}
        </div>
        <div className='flex gap-2'>
          <Button type='button' variant='outline' onClick={onClose}>
            取消
          </Button>
          <Button disabled={mutation.isPending}>保存映射</Button>
        </div>
      </div>
    </form>
  )
}
