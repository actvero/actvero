import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { LoadingState, RequestError } from '@/components/request-state'

export function KnowledgeGrants({
  value,
  onChange,
}: {
  value: string[]
  onChange: (ids: string[]) => void
}) {
  const id = useId()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const path = `/account/access-keys/resources?kind=knowledge&page=${page}&q=${encodeURIComponent(search)}`
  const query = useQuery({
    queryKey: ['knowledge-key-options', id, path],
    queryFn: ({ signal }) =>
      api<Schema['KeyResourcePage']>(path, 'GET', undefined, undefined, signal),
  })
  return (
    <div className='flex flex-col gap-3 rounded-lg border p-3'>
      <Input
        aria-label='查找授权知识库'
        placeholder='搜索知识库…'
        value={search}
        onChange={(e) => {
          setSearch(e.target.value)
          setPage(1)
        }}
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} />
      ) : (
        <>
          <div className='flex max-h-56 flex-col gap-3 overflow-auto'>
            {query.data.items.map((item) => (
              <label className='flex items-center gap-2 text-sm' key={item.id}>
                <Checkbox
                  checked={value.includes(item.id)}
                  onCheckedChange={(checked) =>
                    onChange(
                      checked
                        ? [...value, item.id]
                        : value.filter((v) => v !== item.id)
                    )
                  }
                />
                {item.name}
              </label>
            ))}
            {!query.data.items.length && (
              <p className='text-sm text-muted-foreground'>
                没有可授权的知识库
              </p>
            )}
          </div>
          <div className='flex items-center justify-between'>
            <span className='text-xs text-muted-foreground'>
              已选 {value.length} 个
            </span>
            <div className='flex gap-2'>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </Button>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                disabled={page * 20 >= query.data.total}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
