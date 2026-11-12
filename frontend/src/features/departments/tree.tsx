import { useState } from 'react'
import { Building2, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { departmentTree, type Department } from './data'

type Selection =
  | { selectedId?: string; select: (id: string) => void }
  | {
      selectedIds: string[]
      change: (ids: string[]) => void
      disabled?: boolean
    }

export function DepartmentTree({
  departments,
  selection,
  showArchived = false,
  emptyText = '暂无部门',
}: {
  departments: Department[]
  selection: Selection
  showArchived?: boolean
  emptyText?: string
}) {
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const term = search.trim().toLocaleLowerCase()
  const selectable = 'selectedIds' in selection ? selection : undefined
  const rows = departmentTree(departments)
  const byId = new Map(
    rows.map(({ department }) => [department.id, department])
  )
  const visible = new Set<string>()

  for (const { department, path } of rows) {
    if (
      department.archived &&
      !showArchived &&
      !selectable?.selectedIds.includes(department.id)
    )
      continue
    if (term && !path.toLocaleLowerCase().includes(term)) continue
    let node: Department | undefined = department
    while (node && !visible.has(node.id)) {
      visible.add(node.id)
      node = node.parent_id ? byId.get(node.parent_id) : undefined
    }
  }

  const children = new Map<string | null, typeof rows>()
  for (const row of rows) {
    if (!visible.has(row.department.id)) continue
    const parent = row.department.parent_id ?? null
    const siblings = children.get(parent) ?? []
    siblings.push(row)
    children.set(parent, siblings)
  }

  function branch(parent: string | null, depth: number) {
    return (
      <ul
        className={cn(
          'flex flex-col gap-0.5',
          depth > 0 && depth <= 6 && 'ms-3 border-s ps-2'
        )}
      >
        {(children.get(parent) ?? []).map(({ department, path }) => {
          const id = department.id
          const hasChildren = children.has(id)
          const expanded = Boolean(term) || !collapsed.has(id)
          const checked = selectable?.selectedIds.includes(id) ?? false
          const current =
            'selectedId' in selection && selection.selectedId === id
          return (
            <li key={id}>
              <div
                className={cn(
                  'flex min-w-0 items-center gap-0.5 rounded-md pe-1',
                  (checked || current) && 'bg-accent'
                )}
              >
                {hasChildren ? (
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-8'
                    aria-expanded={expanded}
                    aria-label={`${expanded ? '收起' : '展开'} ${department.name}`}
                    disabled={Boolean(term)}
                    onClick={() => {
                      setCollapsed((previous) => {
                        const next = new Set(previous)
                        if (expanded) next.add(id)
                        else next.delete(id)
                        return next
                      })
                    }}
                  >
                    {expanded ? <ChevronDown /> : <ChevronRight />}
                  </Button>
                ) : (
                  <span className='w-8 shrink-0' aria-hidden='true' />
                )}
                {selectable ? (
                  <label
                    title={path}
                    className='flex min-h-9 min-w-0 flex-1 cursor-pointer items-center gap-2 px-1 text-sm'
                  >
                    <Checkbox
                      checked={checked}
                      aria-label={department.name}
                      disabled={
                        selectable.disabled ||
                        (!checked &&
                          (department.archived ||
                            selectable.selectedIds.length >= 100))
                      }
                      onCheckedChange={(value) =>
                        selectable.change(
                          value === true
                            ? [...selectable.selectedIds, id]
                            : selectable.selectedIds.filter(
                                (selected) => selected !== id
                              )
                        )
                      }
                    />
                    <span className='min-w-0 truncate'>{department.name}</span>
                    {department.archived && (
                      <Badge variant='outline'>已归档</Badge>
                    )}
                  </label>
                ) : (
                  'select' in selection && (
                    <Button
                      type='button'
                      variant='ghost'
                      size='sm'
                      className='min-w-0 flex-1 justify-start'
                      title={path}
                      aria-current={current ? 'true' : undefined}
                      onClick={() => selection.select(id)}
                    >
                      <Building2 data-icon='inline-start' />
                      <span className='min-w-0 truncate'>
                        {department.name}
                      </span>
                      {department.archived && (
                        <Badge variant='outline'>已归档</Badge>
                      )}
                    </Button>
                  )
                )}
              </div>
              {hasChildren && expanded && branch(id, depth + 1)}
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <div className='flex min-w-0 flex-col gap-3'>
      <InputGroup>
        <InputGroupAddon>
          <Search aria-hidden='true' />
        </InputGroupAddon>
        <InputGroupInput
          aria-label='搜索部门'
          placeholder='搜索部门'
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </InputGroup>
      {visible.size ? (
        <ScrollArea
          role='region'
          aria-label='部门列表'
          viewportClassName='max-h-[min(45dvh,28rem)]'
        >
          {branch(null, 0)}
        </ScrollArea>
      ) : (
        <p className='px-2 py-4 text-sm text-muted-foreground'>
          {term ? '没有匹配的部门' : emptyText}
        </p>
      )}
    </div>
  )
}
