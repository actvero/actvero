import type { ReactNode } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { DataTablePagination } from './pagination'

export function ServerTable<T>({
  items,
  columns,
  total,
  page,
  onPage,
  empty,
  onRowClick,
  renderItems,
  getRowId,
}: {
  items: T[]
  columns: ColumnDef<T>[]
  total: number
  page: number
  onPage: (page: number) => void
  empty: string
  /** Keep a native link in a cell for keyboard and modified-click navigation. */
  onRowClick?: (item: T) => void
  /** Alternative presentation that shares the same server pagination. */
  renderItems?: (items: T[]) => ReactNode
  getRowId?: (item: T) => string
}) {
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId,
    manualPagination: true,
    rowCount: total,
    state: { pagination: { pageIndex: page - 1, pageSize: 20 } },
    onPaginationChange: (update) => {
      const next =
        typeof update === 'function'
          ? update({ pageIndex: page - 1, pageSize: 20 })
          : update
      onPage(next.pageIndex + 1)
    },
  })
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      {renderItems ? (
        renderItems(items)
      ) : (
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className={header.column.columnDef.meta?.className}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    interactive={!!onRowClick}
                    onClick={
                      onRowClick
                        ? (event) => {
                            if (
                              event.defaultPrevented ||
                              event.metaKey ||
                              event.ctrlKey ||
                              event.shiftKey ||
                              event.altKey ||
                              window.getSelection()?.toString() ||
                              (event.target as Element).closest(
                                'a, button, input, select, textarea, [role="button"], [role="checkbox"]'
                              )
                            )
                              return
                            onRowClick(row.original)
                          }
                        : undefined
                    }
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        className={cell.column.columnDef.meta?.className}
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className='h-32 text-center'
                  >
                    {empty}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
      <DataTablePagination table={table} />
    </div>
  )
}
