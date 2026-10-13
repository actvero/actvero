import { dateTime } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import type { Channel } from './shared'

export function ListDiagnostic({ channel }: { channel: Channel }) {
  const result = channel.last_diagnostic
  if (!result) return <Badge variant='outline'>未诊断</Badge>
  const label =
    result.status === 'success'
      ? '推理成功'
      : result.status === 'failure'
        ? '推理失败'
        : '结果未确认'
  return (
    <div className='flex min-w-0 flex-col items-start gap-1'>
      <Badge
        variant={
          result.status === 'success'
            ? 'success'
            : result.status === 'failure'
              ? 'destructive'
              : 'outline'
        }
      >
        {label}
      </Badge>
      <span className='max-w-full truncate text-xs text-muted-foreground'>
        {dateTime(result.at)}
        {result.stale ? ' · 旧版本' : ''}
      </span>
    </div>
  )
}
