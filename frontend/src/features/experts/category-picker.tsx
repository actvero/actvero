import type { ComponentProps } from 'react'
import { RequestError } from '@/components/request-state'
import { SearchSelect } from '@/components/search-select'
import { useCategories } from './shared'

export function ExpertCategoryPicker({
  includeAll = false,
  ...props
}: Omit<ComponentProps<typeof SearchSelect>, 'items'> & {
  includeAll?: boolean
}) {
  const query = useCategories()
  const items = (query.data ?? []).map((c) => ({ value: c.id, label: c.name }))
  if (includeAll) items.unshift({ value: 'all', label: '全部类别' })
  return (
    <>
      <SearchSelect
        {...props}
        items={items}
        disabled={props.disabled || !query.data}
        searchPlaceholder='搜索类别…'
        placeholder={query.isPending ? '加载类别…' : '请选择类别'}
      />
      {query.isError && (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      )}
    </>
  )
}
