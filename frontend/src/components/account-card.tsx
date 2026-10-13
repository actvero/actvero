import type { ReactNode } from 'react'
import type { Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  Card,
  CardContent,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import { UserAvatar } from '@/components/user-avatar'

export function AccountCard({
  user,
  action,
  wrapDetails = false,
}: {
  user: Schema['UserView']
  action?: ReactNode
  wrapDetails?: boolean
}) {
  return (
    <Card className='gap-0 py-4'>
      <CardContent className='flex items-center gap-3'>
        <UserAvatar user={user} size='md' className='size-10 shrink-0' />
        <div className='grid min-w-0 flex-1 gap-1'>
          <CardTitle className={cn(wrapDetails ? 'break-all' : 'truncate')}>
            {user.name}
          </CardTitle>
          <CardDescription
            className={cn(wrapDetails ? 'break-all' : 'truncate')}
          >
            {user.email}
          </CardDescription>
        </div>
        {action}
      </CardContent>
    </Card>
  )
}
