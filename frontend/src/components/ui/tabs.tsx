import * as React from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '@/lib/utils'

type TabsVariant = 'default' | 'line' | 'navigation'
const TabsVariantContext = React.createContext<TabsVariant>('default')

function Tabs({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot='tabs'
      className={cn('flex flex-col gap-2', className)}
      {...props}
    />
  )
}

function TabsList({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & {
  variant?: TabsVariant
}) {
  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.List
        data-slot='tabs-list'
        data-variant={variant}
        className={cn(
          'inline-flex items-center text-muted-foreground',
          variant === 'navigation'
            ? 'h-auto w-full flex-col items-stretch justify-start gap-2 bg-transparent p-0'
            : variant === 'line'
              ? 'h-11 w-full justify-start gap-4 border-b bg-transparent p-0'
              : 'h-9 w-fit justify-center rounded-lg bg-muted p-0.75',
          className
        )}
        {...props}
      />
    </TabsVariantContext.Provider>
  )
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  const variant = React.useContext(TabsVariantContext)
  return (
    <TabsPrimitive.Trigger
      data-slot='tabs-trigger'
      className={cn(
        "inline-flex items-center justify-center gap-1.5 text-sm font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        variant === 'navigation'
          ? 'relative w-full flex-none flex-col gap-2 rounded-xl border border-transparent px-2 py-4 text-xs text-muted-foreground hover:bg-background/60 hover:text-foreground data-[state=active]:border-border data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm md:flex-row md:justify-start md:gap-3 md:px-4 md:text-sm'
          : variant === 'line'
            ? '-mb-px h-full min-w-16 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 py-2 text-muted-foreground hover:text-foreground data-[state=active]:border-foreground data-[state=active]:text-foreground'
            : 'h-[calc(100%-1px)] flex-1 rounded-md border border-transparent px-2 py-1 text-foreground data-[state=active]:bg-background data-[state=active]:shadow-sm dark:text-muted-foreground dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 dark:data-[state=active]:text-foreground',
        className
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot='tabs-content'
      className={cn('flex-1 outline-none', className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
