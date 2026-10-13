import { Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip'
import { shortTokens, copyText } from './capability-data'

export function TokenEstimate({
  count,
  total,
}: {
  count?: number
  total?: number
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className='shrink-0 text-xs text-muted-foreground'
          aria-label='工具定义 Token 估算'
        >
          {count === undefined ? '…' : shortTokens(count)}
          {total === undefined ? '' : ` / ${shortTokens(total)}`}
        </span>
      </TooltipTrigger>
      <TooltipContent className='max-w-72'>
        工具名称、有效说明和输入定义的估算（cl100k_base）。
        {total !== undefined && '已选 / 全部；服务关闭时不会注入。'}
        实际占用随模型和客户端而变，不是调用用量或费用。
      </TooltipContent>
    </Tooltip>
  )
}
export function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <Button
      type='button'
      variant='ghost'
      size='icon'
      aria-label={`复制${label}`}
      title={`复制${label}`}
      onClick={() => void copyText(value, label)}
    >
      <Copy />
    </Button>
  )
}
