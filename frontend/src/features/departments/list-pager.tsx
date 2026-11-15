import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function ListPager({
  page,
  total,
  onChange,
}: {
  page: number
  total: number
  onChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / 20))
  if (pages === 1 && page === 1) return null
  return (
    <div className='flex items-center justify-between gap-2 text-xs text-muted-foreground'>
      <span>
        第 {page} / {Math.max(page, pages)} 页
      </span>
      <div className='flex gap-1'>
        <Button
          type='button'
          variant='outline'
          size='icon'
          className='size-8'
          aria-label='上一页'
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft />
        </Button>
        <Button
          type='button'
          variant='outline'
          size='icon'
          className='size-8'
          aria-label='下一页'
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
