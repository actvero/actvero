import { createContext, useContext, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError } from '@/lib/api'
import { useReturnFocus } from '@/hooks/use-return-focus'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { SearchSelect } from '@/components/search-select'
import { useOrganization } from '@/features/auth/session'

export type Category = {
  id: string
  name: string
  count: number
  revision: number
  system: boolean
}
type CategoryDomain = { resource: 'skills' | 'experts'; noun: string }
const CategoryContext = createContext<CategoryDomain>({
  resource: 'skills',
  noun: '技能',
})
function useDomain() {
  const domain = useContext(CategoryContext)
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, domain.resource]
  return {
    ...domain,
    csrf,
    key,
    refresh: () => client.invalidateQueries({ queryKey: key }),
  }
}
function useCategories() {
  const { key, resource } = useDomain()
  return useQuery({
    queryKey: [...key, 'categories', resource],
    queryFn: ({ signal }) =>
      api<Category[]>(
        '/' + resource + '/categories',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
}
function CategoryPicker({
  exclude,
  ...props
}: Omit<React.ComponentProps<typeof SearchSelect>, 'items'> & {
  exclude: string
}) {
  const query = useCategories()
  return (
    <>
      <SearchSelect
        {...props}
        disabled={props.disabled || !query.data}
        items={(query.data ?? [])
          .filter((c) => c.id !== exclude)
          .map((c) => ({ value: c.id, label: c.name }))}
        searchPlaceholder='搜索类别…'
      />
      {query.isError && (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      )}
    </>
  )
}
export function ResourceCategoriesDialog({
  resource,
  noun,
  close,
}: CategoryDomain & { close: () => void }) {
  return (
    <CategoryContext.Provider value={{ resource, noun }}>
      <CategoriesDialog close={close} />
    </CategoryContext.Provider>
  )
}

const nameSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, '请输入类别名称')
    .max(30, '名称最多 30 个字符'),
})
const deleteSchema = z.object({
  target_id: z.string().min(1, '请选择接收资源的类别'),
})

function CategoryNameForm({
  category,
  busy,
  save,
  cancel,
}: {
  category?: Category
  busy: boolean
  save: (name: string) => Promise<boolean>
  cancel: () => void
}) {
  const form = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: category?.name ?? '' },
  })
  return (
    <Form {...form}>
      <form
        className='flex flex-wrap items-start gap-3'
        onSubmit={form.handleSubmit(async (values) => {
          if (await save(values.name)) form.reset({ name: '' })
        })}
      >
        <FormField
          control={form.control}
          name='name'
          render={({ field }) => (
            <FormItem className='min-w-0 flex-1'>
              <FormLabel>{category ? '编辑类别名称' : '新增类别'}</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  autoFocus={!!category}
                  maxLength={30}
                  placeholder='输入类别名称'
                  disabled={busy}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='flex gap-2 pt-6'>
          <Button disabled={busy}>
            {!category && <Plus />}
            {category ? '保存' : '新增'}
          </Button>
          {category && (
            <Button
              type='button'
              variant='outline'
              disabled={busy}
              onClick={cancel}
            >
              取消
            </Button>
          )}
        </div>
      </form>
    </Form>
  )
}

function DeleteCategory({
  category,
  close,
  done,
}: {
  category: Category
  close: () => void
  done: () => Promise<void>
}) {
  const { csrf, resource, noun } = useDomain()
  const query = useCategories()
  const [error, setError] = useState<unknown>()
  const [review, setReview] = useState(category)
  const form = useForm<z.infer<typeof deleteSchema>>({
    resolver: zodResolver(deleteSchema),
    defaultValues: { target_id: 'uncategorized' },
  })
  const busy = form.formState.isSubmitting
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => !open && !busy && close()}
      title={`删除“${review.name}”`}
      desc={
        review.count
          ? `此类别关联 ${review.count} 个${noun}。请选择迁移位置，内容、版本和使用范围会保留。`
          : `此类别没有关联${noun}，删除后将不再出现在类别选项中。`
      }
      confirmText={busy ? '删除中…' : review.count ? '迁移并删除' : '删除类别'}
      cancelBtnText='取消'
      destructive
      isLoading={busy}
      form='delete-category'
    >
      <Form {...form}>
        <form
          id='delete-category'
          className='flex flex-col gap-4'
          onSubmit={form.handleSubmit(async (values) => {
            setError(undefined)
            try {
              await api(
                `/${resource}/categories/${review.id}`,
                'DELETE',
                { ...values, revision: review.revision, count: review.count },
                csrf
              )
              await done()
              toast.success('类别已删除')
              close()
            } catch (e) {
              setError(e)
            }
          })}
        >
          {review.count > 0 && (
            <FormField
              control={form.control}
              name='target_id'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{noun}迁移到</FormLabel>
                  <FormControl>
                    <CategoryPicker
                      value={field.value}
                      onValueChange={field.onChange}
                      ref={field.ref}
                      onBlur={field.onBlur}
                      exclude={review.id}
                      className='w-full'
                      disabled={busy}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
          {error != null && (
            <RequestError
              error={error}
              retry={() => {
                void query.refetch().then((result) => {
                  const current = result.data?.find(
                    (item) => item.id === review.id
                  )
                  if (current) {
                    setReview(current)
                    setError(undefined)
                  } else if (result.data) {
                    void done()
                    close()
                  }
                })
              }}
            />
          )}
        </form>
      </Form>
    </ConfirmDialog>
  )
}

function CategoriesDialog({ close }: { close: () => void }) {
  const { csrf, refresh, resource, noun } = useDomain()
  const query = useCategories()
  const restoreFocus = useReturnFocus()
  const [editing, setEditing] = useState<Category>()
  const [deleting, setDeleting] = useState<Category>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  async function mutate(path: string, method: string, body: unknown) {
    setBusy(true)
    setError(undefined)
    try {
      await api('/' + resource + '/categories' + path, method, body, csrf)
      await refresh()
      return true
    } catch (e) {
      setError(e)
      if (e instanceof ApiError && e.status === 409) await query.refetch()
      return false
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !busy && !deleting && close()}
    >
      <DialogContent
        className='flex max-h-[85dvh] flex-col sm:max-w-2xl'
        onCloseAutoFocus={restoreFocus}
      >
        <DialogHeader>
          <DialogTitle>类别管理</DialogTitle>
          <DialogDescription>
            管理{noun}类别与展示顺序。修改后同步到{noun}目录。
          </DialogDescription>
        </DialogHeader>
        <CategoryNameForm
          key={editing?.id ?? 'new'}
          category={editing}
          busy={busy}
          cancel={() => {
            setEditing(undefined)
            setError(undefined)
          }}
          save={async (name) => {
            const ok = await mutate(
              editing ? `/${editing.id}` : '',
              editing ? 'PATCH' : 'POST',
              editing ? { name, revision: editing.revision } : { name }
            )
            if (ok) {
              setEditing(undefined)
              toast.success(editing ? '类别名称已保存' : '类别已新增')
            }
            return ok
          }}
        />
        {error != null && (
          <RequestError
            error={error}
            retry={() => {
              void query.refetch().then((result) => {
                if (editing)
                  setEditing(
                    result.data?.find((item) => item.id === editing.id)
                  )
                setError(undefined)
              })
            }}
          />
        )}
        <Separator />
        <div className='min-h-0 flex-1 overflow-y-auto'>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            <ul className='flex flex-col gap-1' aria-label={`${noun}类别列表`}>
              {query.data.map((category, index) => (
                <li
                  key={category.id}
                  className='flex min-w-0 items-center gap-3 py-2'
                  aria-label={category.name}
                >
                  <div className='flex min-w-0 flex-1 flex-col gap-1'>
                    <span className='truncate'>{category.name}</span>
                    <span className='text-sm text-muted-foreground'>
                      {category.count} 个{noun}
                      {category.system ? ' · 系统保留，固定末尾' : ''}
                    </span>
                  </div>
                  {!category.system && (
                    <>
                      <Button
                        variant='ghost'
                        size='icon'
                        aria-label={`上移${category.name}`}
                        disabled={busy || index === 0}
                        onClick={() =>
                          void mutate(`/${category.id}/move`, 'POST', {
                            direction: 'up',
                            revision: category.revision,
                          })
                        }
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        variant='ghost'
                        size='icon'
                        aria-label={`下移${category.name}`}
                        disabled={
                          busy ||
                          index ===
                            query.data.filter((item) => !item.system).length - 1
                        }
                        onClick={() =>
                          void mutate(`/${category.id}/move`, 'POST', {
                            direction: 'down',
                            revision: category.revision,
                          })
                        }
                      >
                        <ArrowDown />
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant='ghost'
                            size='icon'
                            disabled={busy}
                            aria-label={`${category.name}的操作`}
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align='end'>
                          <DropdownMenuGroup>
                            <DropdownMenuItem
                              onSelect={() => {
                                setEditing(category)
                                setError(undefined)
                              }}
                            >
                              <Pencil />
                              编辑名称
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant='destructive'
                              onSelect={() => setDeleting(category)}
                            >
                              <Trash2 />
                              删除类别
                            </DropdownMenuItem>
                          </DropdownMenuGroup>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <DialogFooter>
          <Button variant='outline' disabled={busy} onClick={close}>
            完成
          </Button>
        </DialogFooter>
        {deleting && (
          <DeleteCategory
            category={deleting}
            close={() => setDeleting(undefined)}
            done={async () => {
              setEditing(undefined)
              await refresh()
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
