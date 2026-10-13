import type { Schema } from '@/lib/api'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'

export function UserAvatar({
  user,
  className,
  size = 'sm',
}: {
  user: Pick<Schema['UserView'], 'name' | 'avatar_url'>
  className?: string
  size?: 'sm' | 'md' | 'lg'
}) {
  return (
    <Avatar className={className} size={size}>
      {user.avatar_url && <AvatarImage src={user.avatar_url} alt='' />}
      <AvatarFallback size={size}>
        {Array.from(user.name.trim()).slice(-2).join('')}
      </AvatarFallback>
    </Avatar>
  )
}
