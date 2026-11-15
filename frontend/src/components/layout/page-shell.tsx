import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Header } from './header'
import { Main } from './main'
import { PageHeader } from './page-header'

export function PageShell({
  title,
  titleBefore,
  titleAfter,
  description,
  action,
  compact = false,
  fixedContent = false,
  children,
}: {
  title?: string
  titleBefore?: ReactNode
  titleAfter?: ReactNode
  description?: string
  action?: ReactNode
  compact?: boolean
  fixedContent?: boolean
  children: ReactNode
}) {
  return (
    <>
      <Header fixed className={compact ? 'h-14' : undefined}>
        <Search className='me-auto' />
        <ThemeSwitch />
      </Header>
      <Main
        fixed={fixedContent}
        className={cn('flex flex-1 flex-col gap-6', compact && 'gap-3 py-2')}
      >
        {(title || action) && (
          <PageHeader
            title={title}
            titleBefore={titleBefore}
            titleAfter={titleAfter}
            description={description}
            action={action}
          />
        )}
        {children}
      </Main>
    </>
  )
}
