import type { ReactNode } from 'react'
import { Camera } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'

type ResourceIconProps = {
  image?: string | null
  name: string
  size?: 'sm' | 'md' | 'lg'
  fallback?: ReactNode
}

export function ResourceIcon({
  image,
  name,
  size = 'md',
  fallback,
}: ResourceIconProps) {
  return (
    <Avatar size={size}>
      <AvatarImage src={image || undefined} alt='' />
      <AvatarFallback size={size}>
        {fallback ?? (Array.from(name.trim())[0]?.toUpperCase() || 'S')}
      </AvatarFallback>
    </Avatar>
  )
}

export function ResourceIconButton({
  label,
  disabled,
  onClick,
  size = 'lg',
  showCamera = true,
  ...icon
}: ResourceIconProps & {
  label: string
  disabled?: boolean
  onClick: () => void
  showCamera?: boolean
}) {
  return (
    <Button
      type='button'
      variant='ghost'
      className={cn('relative h-auto shrink-0', showCamera ? 'p-1' : 'p-0.5')}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      <ResourceIcon {...icon} size={size} />
      {showCamera && (
        <Camera className='absolute end-0 bottom-0 size-4' aria-hidden />
      )}
    </Button>
  )
}
