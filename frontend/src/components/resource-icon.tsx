import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'

export function ResourceIcon({
  image,
  name,
  size = 'md',
}: {
  image?: string | null
  name: string
  size?: 'sm' | 'md' | 'lg'
}) {
  return (
    <Avatar size={size}>
      <AvatarImage src={image || undefined} alt='' />
      <AvatarFallback size={size}>
        {Array.from(name.trim())[0]?.toUpperCase() || 'S'}
      </AvatarFallback>
    </Avatar>
  )
}
