import type { ReactNode } from 'react'
import { Card } from '@/components/ui/card'

export function ResourceCard({
  name,
  description,
  icon,
  status,
  metadata,
  onOpen,
}: {
  name: string
  description?: string
  icon?: ReactNode
  status?: ReactNode
  metadata?: ReactNode
  onOpen: () => void
}) {
  return (
    <Card
      asChild
      density='compact'
      className='min-w-0 cursor-pointer gap-3 px-4 py-3.5 text-start shadow-none transition-colors hover:border-ring/50 hover:bg-accent/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring'
    >
      <button type='button' onClick={onOpen}>
        <span className='flex w-full min-w-0 flex-col gap-1.5'>
          <span className='flex min-h-8 min-w-0 items-center gap-2.5'>
            {icon && (
              <span className='flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground [&>svg]:size-4'>
                {icon}
              </span>
            )}
            <span
              className='min-w-0 flex-1 truncate text-base leading-snug font-semibold'
              title={name}
            >
              {name}
            </span>
            {status}
          </span>
          {description?.trim() && (
            <span
              className='line-clamp-2 text-sm wrap-anywhere text-muted-foreground'
              title={description}
            >
              {description}
            </span>
          )}
        </span>
        {metadata != null && (
          <span className='mt-auto w-full text-xs leading-5 text-muted-foreground tabular-nums'>
            {metadata}
          </span>
        )}
      </button>
    </Card>
  )
}
