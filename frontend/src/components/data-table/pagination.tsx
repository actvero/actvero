import type { Table } from '@tanstack/react-table'
import { ListPagination } from '@/components/list-pagination'

export function DataTablePagination<T>({
  table,
  className,
}: {
  table: Table<T>
  className?: string
}) {
  return (
    <ListPagination
      total={table.getRowCount()}
      page={table.getState().pagination.pageIndex + 1}
      pageCount={table.getPageCount()}
      pageSize={table.getState().pagination.pageSize}
      onPage={(page) => table.setPageIndex(page - 1)}
      className={className}
    />
  )
}
