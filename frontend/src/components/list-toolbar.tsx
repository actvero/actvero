import type { ComponentProps, ReactNode } from 'react'
import { Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'

export function ListToolbar({
  children,
  actions,
}: {
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className='flex shrink-0 flex-wrap items-center gap-3'>
      {children}
      {actions && (
        <div className='ms-auto flex flex-wrap items-center gap-2'>
          {actions}
        </div>
      )}
    </div>
  )
}

export function ListSearch({
  className,
  ...props
}: ComponentProps<typeof InputGroupInput>) {
  return (
    <InputGroup className={cn('w-full sm:w-80', className)}>
      <InputGroupAddon>
        <Search />
      </InputGroupAddon>
      <InputGroupInput type='search' {...props} />
    </InputGroup>
  )
}
