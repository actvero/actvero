import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cn } from '@/lib/utils'

function Card({
  className,
  density = 'default',
  tone = 'default',
  asChild = false,
  interactive = false,
  ...props
}: React.ComponentProps<'div'> & {
  density?: 'default' | 'compact'
  tone?: 'default' | 'muted'
  asChild?: boolean
  interactive?: boolean
}) {
  const Comp = asChild ? Slot : 'div'
  return (
    <Comp
      data-slot='card'
      className={cn(
        'flex flex-col gap-6 rounded-xl border bg-card py-6 text-card-foreground shadow-sm',
        tone === 'muted' && 'bg-muted/20',
        density === 'compact' && 'gap-0 py-2',
        interactive &&
          'cursor-pointer transition-[border-color,box-shadow] hover:border-ring/50 hover:shadow-md focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
        className
      )}
      {...props}
    />
  )
}

function CardHeader({
  className,
  layout = 'default',
  ...props
}: React.ComponentProps<'div'> & { layout?: 'default' | 'row' }) {
  return (
    <div
      data-slot='card-header'
      className={cn(
        layout === 'row'
          ? '@container/card-header flex items-center px-4'
          : '@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6',
        className
      )}
      {...props}
    />
  )
}

function CardTitle({
  className,
  size = 'default',
  ...props
}: React.ComponentProps<'div'> & { size?: 'default' | 'body' }) {
  return (
    <div
      data-slot='card-title'
      className={cn(
        'leading-none font-semibold',
        size === 'body' && 'text-sm leading-5 font-normal',
        className
      )}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card-description'
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card-action'
      className={cn(
        'col-start-2 row-span-2 row-start-1 self-start justify-self-end',
        className
      )}
      {...props}
    />
  )
}

function CardContent({
  className,
  tone = 'default',
  ...props
}: React.ComponentProps<'div'> & { tone?: 'default' | 'muted' }) {
  return (
    <div
      data-slot='card-content'
      className={cn('px-6', tone === 'muted' && 'bg-muted/30', className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card-footer'
      className={cn('flex items-center px-6 [.border-t]:pt-6', className)}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
