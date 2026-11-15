import type { ComponentProps, ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export type PageHeaderProps = {
  title?: string
  titleBefore?: ReactNode
  titleAfter?: ReactNode
  description?: string
  action?: ReactNode
  truncateTitle?: boolean
}

export function PageBack({
  label,
  children,
  ...props
}: Omit<ComponentProps<typeof Button>, 'variant' | 'size' | 'aria-label'> & {
  label: string
}) {
  return (
    <Button variant='ghost' size='icon' aria-label={label} {...props}>
      {children ?? <ArrowLeft />}
    </Button>
  )
}

export function PageHeader({
  title,
  titleBefore,
  titleAfter,
  description,
  action,
  truncateTitle = false,
}: PageHeaderProps) {
  return (
    <div className='flex shrink-0 flex-wrap items-center justify-between gap-4'>
      <div className='flex min-w-0 flex-1 items-start gap-3'>
        {titleBefore}
        <div className='flex min-w-0 flex-col gap-1'>
          <div
            className={cn(
              'flex min-h-9 items-center gap-x-3 gap-y-2',
              !truncateTitle && 'flex-wrap'
            )}
          >
            {title && (
              <h1
                className={cn(
                  'max-w-full min-w-0 text-2xl font-bold tracking-tight',
                  truncateTitle ? 'truncate' : '[overflow-wrap:anywhere]'
                )}
                title={truncateTitle ? title : undefined}
              >
                {title}
              </h1>
            )}
            {titleAfter}
          </div>
          {description && (
            <p className='text-sm break-words text-muted-foreground'>
              {description}
            </p>
          )}
        </div>
      </div>
      {action && (
        <div className='flex max-w-full flex-wrap items-center gap-2 max-sm:basis-full max-sm:justify-end'>
          {action}
        </div>
      )}
    </div>
  )
}
