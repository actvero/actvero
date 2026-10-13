import { AlertCircle } from 'lucide-react'
import { messageOf } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function RequestError({
  error,
  retry,
}: {
  error: unknown
  retry?: () => void
}) {
  return (
    <Alert variant='destructive'>
      <AlertCircle />
      <AlertTitle>暂时无法完成</AlertTitle>
      <AlertDescription>
        <span>{messageOf(error)}</span>
        {retry && (
          <Button type='button' variant='outline' size='sm' onClick={retry}>
            重试
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}
export function LoadingState() {
  return (
    <div
      role='status'
      aria-label='正在加载'
      className='flex flex-col gap-4 p-6'
    >
      <Skeleton className='h-8 w-40' />
      <Skeleton className='h-32 w-full' />
      <span className='sr-only'>正在加载…</span>
    </div>
  )
}
