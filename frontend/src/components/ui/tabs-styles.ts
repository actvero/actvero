import { cn } from '@/lib/utils'

export type TabsVariant = 'default' | 'line' | 'navigation'

export function tabsListStyles(variant: TabsVariant) {
  return cn(
    'inline-flex items-center text-muted-foreground',
    variant === 'navigation'
      ? 'h-auto w-full flex-col items-stretch justify-start gap-2 bg-transparent p-0'
      : variant === 'line'
        ? 'h-11 w-full shrink-0 justify-start gap-4 overflow-x-auto border-b bg-transparent p-0'
        : 'h-9 w-fit justify-center rounded-lg bg-muted p-0.75'
  )
}

export function tabsTriggerStyles(variant: TabsVariant) {
  return cn(
    "inline-flex items-center justify-center gap-1.5 text-sm font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
    variant === 'navigation'
      ? 'relative w-full flex-none flex-col gap-2 rounded-xl border border-transparent px-2 py-4 text-xs text-muted-foreground hover:bg-background/60 hover:text-foreground aria-selected:border-border aria-selected:bg-background aria-selected:text-foreground aria-selected:shadow-sm md:flex-row md:justify-start md:gap-3 md:px-4 md:text-sm'
      : variant === 'line'
        ? '-mb-px h-full min-w-16 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 py-2 text-muted-foreground hover:text-foreground aria-selected:border-foreground aria-selected:text-foreground'
        : 'h-[calc(100%-1px)] flex-1 rounded-md border border-transparent px-2 py-1 text-foreground aria-selected:bg-background aria-selected:shadow-sm dark:text-muted-foreground dark:aria-selected:border-input dark:aria-selected:bg-input/30 dark:aria-selected:text-foreground'
  )
}
