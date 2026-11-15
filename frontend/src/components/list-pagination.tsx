import {
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'

export type ListPaginationProps = {
  total?: number
  page: number
  pageCount: number
  onPage: (page: number) => void
  pageSize?: number
  onPageSize?: (size: number) => void
  pageSizeOptions?: readonly number[]
  disabled?: boolean
  label?: string
  unit?: string
  className?: string
}

export function ListPagination({
  total,
  page,
  pageCount,
  onPage,
  pageSize,
  onPageSize,
  pageSizeOptions = [10, 20, 30, 40, 50, 100],
  disabled = false,
  label = '列表分页',
  unit = '条',
  className,
}: ListPaginationProps) {
  const pages = Math.max(1, pageCount)
  const previousDisabled = disabled || page <= 1
  const nextDisabled = disabled || page >= pages
  return (
    <div className={cn('mt-auto flex shrink-0 flex-col gap-4', className)}>
      <Separator />
      <nav
        aria-label={label}
        className='flex min-w-0 flex-wrap items-center justify-between gap-3'
      >
        <p className='text-sm text-muted-foreground'>
          共 {total === undefined ? '—' : total.toLocaleString('zh-CN')} {unit}
          {pageSize && !onPageSize ? `，每页 ${pageSize} 条` : ''}
        </p>
        <div className='ms-auto flex flex-wrap items-center gap-3'>
          {onPageSize && pageSize && (
            <Select
              value={String(pageSize)}
              onValueChange={(value) => onPageSize(Number(value))}
              disabled={disabled}
            >
              <SelectTrigger aria-label='每页条数'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent side='top'>
                <SelectGroup>
                  {[...new Set([...pageSizeOptions, pageSize])]
                    .sort((a, b) => a - b)
                    .map((size) => (
                      <SelectItem key={size} value={String(size)}>
                        {size} 条 / 页
                      </SelectItem>
                    ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          )}
          <span
            className='text-sm text-muted-foreground tabular-nums'
            aria-live='polite'
          >
            第 {page} / {pages} 页
          </span>
          <div className='flex items-center gap-2'>
            {pages > 2 && (
              <Button
                className='max-sm:hidden'
                variant='outline'
                size='icon'
                aria-label='首页'
                disabled={previousDisabled}
                onClick={() => onPage(1)}
              >
                <ChevronFirst />
              </Button>
            )}
            <Button
              variant='outline'
              size='icon'
              aria-label='上一页'
              disabled={previousDisabled}
              onClick={() => onPage(page - 1)}
            >
              <ChevronLeft />
            </Button>
            <Button
              variant='outline'
              size='icon'
              aria-label='下一页'
              disabled={nextDisabled}
              onClick={() => onPage(page + 1)}
            >
              <ChevronRight />
            </Button>
            {pages > 2 && (
              <Button
                className='max-sm:hidden'
                variant='outline'
                size='icon'
                aria-label='末页'
                disabled={nextDisabled}
                onClick={() => onPage(pages)}
              >
                <ChevronLast />
              </Button>
            )}
          </div>
        </div>
      </nav>
    </div>
  )
}
