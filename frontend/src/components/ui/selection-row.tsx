import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'
import { Label } from './label'

export function SelectionRow({
  className,
  ...props
}: ComponentProps<typeof Label>) {
  return (
    <Label
      {...props}
      className={cn(
        'flex cursor-pointer items-center gap-3 rounded-md px-3 py-3 font-normal transition-colors focus-within:bg-accent hover:bg-accent has-[[data-disabled]]:cursor-default',
        className
      )}
    />
  )
}
