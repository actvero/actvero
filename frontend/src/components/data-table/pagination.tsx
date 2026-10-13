import type { Table } from '@tanstack/react-table'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export function DataTablePagination<T>({
  table,
  className,
}: {
  table: Table<T>
  className?: string
}) {
  const pages = Math.max(1, table.getPageCount())
  return (
    <div
      className={cn(
        'flex flex-wrap items-center justify-between gap-4',
        className
      )}
    >
      <p className='text-sm text-muted-foreground'>
        共 {table.getRowCount()} 条，每页 {table.getState().pagination.pageSize}{' '}
        条
      </p>
      <div className='flex items-center gap-3'>
        <span className='text-sm text-muted-foreground'>
          第 {table.getState().pagination.pageIndex + 1} / {pages} 页
        </span>
        <Button
          variant='outline'
          size='icon'
          aria-label='上一页'
          onClick={() => table.previousPage()}
          disabled={!table.getCanPreviousPage()}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant='outline'
          size='icon'
          aria-label='下一页'
          onClick={() => table.nextPage()}
          disabled={!table.getCanNextPage()}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
