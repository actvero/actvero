import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Header } from './header'
import { Main } from './main'

export function PageShell({
  title,
  titleAfter,
  description,
  action,
  compact = false,
  fixedContent = false,
  children,
}: {
  title?: string
  titleAfter?: ReactNode
  description?: string
  action?: ReactNode
  compact?: boolean
  fixedContent?: boolean
  children: ReactNode
}) {
  return (
    <>
      <Header fixed>
        <Search className='me-auto' />
        <ThemeSwitch />
      </Header>
      <Main
        fixed={fixedContent}
        className={cn('flex flex-1 flex-col gap-6', compact && 'gap-4 py-4')}
      >
        {(title || action) && (
          <div className='flex flex-wrap items-end justify-between gap-4'>
            <div>
              <div className='flex flex-wrap items-center gap-3'>
                <h1
                  className={cn(
                    'text-2xl font-bold tracking-tight',
                    compact && 'text-xl'
                  )}
                >
                  {title}
                </h1>
                {titleAfter}
              </div>
              {description && (
                <p className='mt-1 text-muted-foreground'>{description}</p>
              )}
            </div>
            {action}
          </div>
        )}
        {children}
      </Main>
    </>
  )
}
