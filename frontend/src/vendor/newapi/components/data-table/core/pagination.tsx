/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import type { Table } from '@tanstack/react-table'
import { ListPagination } from '@/components/list-pagination'

type DataTablePaginationProps<TData> = {
  table: Table<TData>
  compact?: boolean
}

export function DataTablePagination<TData>({
  table,
  compact = false,
}: DataTablePaginationProps<TData>) {
  const { pageIndex, pageSize } = table.getState().pagination
  return (
    <ListPagination
      total={table.getRowCount()}
      page={pageIndex + 1}
      pageCount={table.getPageCount()}
      pageSize={pageSize}
      onPage={(page) => table.setPageIndex(page - 1)}
      onPageSize={compact ? undefined : (size) => table.setPageSize(size)}
    />
  )
}
