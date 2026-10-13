import * as React from 'react'
import * as AvatarPrimitive from '@radix-ui/react-avatar'
import { cn } from '@/lib/utils'

function Avatar({
  className,
  size = 'sm',
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Root> & {
  size?: 'sm' | 'md' | 'lg'
}) {
  return (
    <AvatarPrimitive.Root
      data-slot='avatar'
      className={cn(
        'relative flex shrink-0 overflow-hidden rounded-full',
        size === 'sm' && 'size-8',
        size === 'md' && 'size-10',
        size === 'lg' && 'size-16',
        className
      )}
      {...props}
    />
  )
}

function AvatarImage({
  className,
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Image>) {
  return (
    <AvatarPrimitive.Image
      data-slot='avatar-image'
      className={cn('aspect-square size-full object-cover', className)}
      {...props}
    />
  )
}

function AvatarFallback({
  className,
  size = 'default',
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Fallback> & {
  size?: 'default' | 'sm' | 'md' | 'lg'
}) {
  return (
    <AvatarPrimitive.Fallback
      data-slot='avatar-fallback'
      className={cn(
        'flex size-full items-center justify-center rounded-full bg-muted',
        size === 'sm' && 'text-sm',
        size === 'md' && 'text-base',
        size === 'lg' && 'text-xl',
        className
      )}
      {...props}
    />
  )
}

export { Avatar, AvatarImage, AvatarFallback }
