import type { ComponentProps } from 'react'
import { RequestError } from '@/components/request-state'
import { SearchSelect } from '@/components/search-select'
import { useCategories } from './categories-query'

export function CategoryPicker({
  includeAll = false,
  exclude,
  ...props
}: Omit<ComponentProps<typeof SearchSelect>, 'items'> & {
  includeAll?: boolean
  exclude?: string
}) {
  const query = useCategories()
  const items = (query.data ?? [])
    .filter((item) => item.id !== exclude)
    .map((item) => ({ value: item.id, label: item.name }))
  if (includeAll) items.unshift({ value: 'all', label: '全部类别' })
  return (
    <>
      <SearchSelect
        {...props}
        disabled={props.disabled || query.isPending || query.isError}
        items={items}
        placeholder={query.isPending ? '加载类别…' : '类别已删除，请重新选择'}
        searchPlaceholder='搜索类别…'
      />
      {query.isError && (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      )}
    </>
  )
}
