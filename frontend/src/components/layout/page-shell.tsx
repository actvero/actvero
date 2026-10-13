import type { ReactNode } from 'react'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Header } from './header'
import { Main } from './main'

export function PageShell({
  title,
  titleAfter,
  description,
  action,
  children,
}: {
  title?: string
  titleAfter?: ReactNode
  description?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <>
      <Header fixed>
        <Search className='me-auto' />
        <ThemeSwitch />
      </Header>
      <Main className='flex flex-1 flex-col gap-6'>
        {(title || action) && (
          <div className='flex flex-wrap items-end justify-between gap-4'>
            <div>
              <div className='flex flex-wrap items-center gap-3'>
                <h1 className='text-2xl font-bold tracking-tight'>{title}</h1>
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
