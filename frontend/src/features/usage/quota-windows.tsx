import { useId } from 'react'
import { dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

type Window = Schema['WindowView']

function formatPoints(value: string) {
  const [whole, fraction = ''] = value.split('.')
  const rounded = fraction.slice(0, 4).replace(/0+$/, '')
  const shortened = /[1-9]/.test(fraction.slice(4))
  if (whole === '0' && !rounded && shortened) return '< 0.0001'
  return `${shortened ? '≈ ' : ''}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${rounded ? '.' + rounded : ''}`
}

export function Points({ value }: { value: string }) {
  const display = formatPoints(value)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className='tabular-nums'
          aria-label={`${value} 积分`}
        >
          {display}
        </span>
      </TooltipTrigger>
      <TooltipContent>{value} 积分</TooltipContent>
    </Tooltip>
  )
}

function windowLabel(w: Window) {
  return w.rule.kind === 'fixed_hours' ? `${w.rule.hours} 小时` : '每周'
}

export function QuotaWindow({
  window: w,
  compact = false,
}: {
  window: Window
  compact?: boolean
}) {
  const id = useId()
  const cap = String(w.rule.points)
  const capNumber = Number(cap)
  const percent =
    capNumber > 0
      ? Math.max(0, Math.min(100, (Number(w.remaining) / capNumber) * 100))
      : 0
  const percentText =
    percent > 0 && percent < 0.1
      ? '< 0.1%'
      : percent < 100 && percent > 99.9
        ? '> 99.9%'
        : `${Math.floor(percent * 10) / 10}%`
  return (
    <section className='flex min-w-0 flex-col gap-2' aria-labelledby={id}>
      <div className='flex flex-wrap items-center justify-between gap-x-4 gap-y-1'>
        <span id={id} className='font-medium'>
          {windowLabel(w)}
        </span>
        {capNumber === 0 ? (
          <Badge variant='outline'>零额度</Badge>
        ) : (
          <span className='text-sm text-muted-foreground'>
            剩余 {percentText}
          </span>
        )}
      </div>
      {!compact && (
        <div className='flex flex-wrap items-baseline gap-1'>
          <span className='text-2xl font-semibold'>
            <Points value={w.remaining} />
          </span>
          <span className='text-sm text-muted-foreground'>
            / <Points value={cap} /> 积分
          </span>
        </div>
      )}
      <Progress
        value={percent}
        aria-label={`${windowLabel(w)}剩余额度`}
        aria-valuetext={`剩余 ${w.remaining} / ${cap} 积分；已用 ${w.used}；预占 ${w.reserved}`}
      />
      <div className='flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground'>
        {compact ? (
          <span>
            剩余 <Points value={w.remaining} /> / <Points value={cap} /> 积分
          </span>
        ) : (
          <span>
            已用 <Points value={w.used} /> 积分
          </span>
        )}
        {Number(w.reserved) > 0 && (
          <span>
            预占 <Points value={w.reserved} /> 积分
          </span>
        )}
      </div>
      <p className='text-xs text-muted-foreground'>
        {w.resets_at ? `${dateTime(w.resets_at)} 恢复` : '首次使用后起算'}
      </p>
    </section>
  )
}
