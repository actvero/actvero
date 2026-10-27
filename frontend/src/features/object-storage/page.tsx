import { useState } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Field, FieldLabel, FieldGroup } from '@/components/ui/field'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { Editor, TextField } from '@/components/settings-editor'
import { useSession } from '@/features/auth/session'

type Storage = Schema['StorageView']
type EditorProps<T> = {
  saved: T | null
  csrf?: string
  close: () => void
  changed: () => Promise<void>
}
const queryKey = ['platform', 'object-storage'] as const
export function ObjectStoragePage() {
  const { data: session } = useSession()
  const cache = useQueryClient()
  const [editing, setEditing] = useState<Storage | 'new' | null>(null)
  const query = useQuery({
    queryKey,
    queryFn: () => api<{ items: Storage[] }>('/platform/object-storage'),
    retry: false,
  })
  const changed = async () => {
    await cache.invalidateQueries({ queryKey })
    await cache.invalidateQueries({
      queryKey: ['platform', 'client-distribution'],
    })
  }
  const test = useMutation({
    mutationFn: (id: string) =>
      api<Schema['Message']>(
        '/platform/object-storage/' + id + '/test',
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: (v) => toast.success(v.message),
  })
  return (
    <PageShell
      title='对象存储'
      action={
        <Button disabled={!query.data} onClick={() => setEditing('new')}>
          <Plus />
          添加存储
        </Button>
      }
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <div className='space-y-4'>
          {!query.data.items.length && (
            <p className='py-10 text-center text-muted-foreground'>
              尚未配置对象存储
            </p>
          )}
          {query.data.items.map((s) => (
            <Card key={s.id}>
              <CardHeader>
                <CardTitle>
                  {s.name} {s.is_default && <Badge>默认</Badge>}{' '}
                  {!s.enabled && <Badge variant='secondary'>已停用</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-3'>
                <p className='text-sm text-muted-foreground'>
                  {s.bucket} · {s.region}
                </p>
                <div className='flex gap-2'>
                  <Button variant='outline' onClick={() => setEditing(s)}>
                    编辑
                  </Button>
                  <Button
                    variant='outline'
                    disabled={test.isPending || !s.enabled}
                    onClick={() => test.mutate(s.id)}
                  >
                    测试连接
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {test.isError && <RequestError error={test.error} />}
      {editing && (
        <StorageEditor
          saved={editing === 'new' ? null : editing}
          csrf={session?.csrf}
          close={() => setEditing(null)}
          changed={changed}
        />
      )}
    </PageShell>
  )
}
const storageSchema = z.object({
  name: z.string().trim().min(1, '请填写名称'),
  endpoint: z.url(),
  region: z.string().min(1),
  bucket: z.string().min(3),
  prefix: z.string().min(1),
  public_url: z.union([z.literal(''), z.url()]),
  access_key: z.string(),
  secret_key: z.string(),
  path_style: z.boolean(),
  enabled: z.boolean(),
  is_default: z.boolean(),
})
function StorageEditor({ saved, csrf, close, changed }: EditorProps<Storage>) {
  const [ident] = useState(saved?.id || crypto.randomUUID())
  const form = useForm({
    resolver: zodResolver(storageSchema),
    defaultValues: {
      name: saved?.name || '',
      endpoint: saved?.endpoint || '',
      region: saved?.region || 'us-east-1',
      bucket: saved?.bucket || '',
      prefix: saved?.prefix || 'actvero',
      public_url: saved?.public_url || '',
      access_key: '',
      secret_key: '',
      path_style: saved?.path_style || false,
      enabled: saved?.enabled ?? true,
      is_default: saved?.is_default ?? true,
    },
  })
  const options = useWatch({ control: form.control })
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof storageSchema>) =>
      api(
        '/platform/object-storage/' + ident,
        'PUT',
        {
          ...values,
          expected_revision: saved?.revision || 0,
          access_key: values.access_key || null,
          secret_key: values.secret_key || null,
        },
        csrf
      ),
    onSuccess: async () => {
      await changed()
      close()
    },
  })
  return (
    <Editor
      title={saved ? '编辑对象存储' : '添加对象存储'}
      busy={mutation.isPending}
      close={close}
    >
      <form
        onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
        className='space-y-5'
      >
        <FieldGroup>
          {(
            [
              ['name', '名称'],
              ['endpoint', 'S3 服务地址'],
              ['region', '区域'],
              ['bucket', 'Bucket'],
              ['access_key', saved ? '访问密钥（留空保留）' : '访问密钥'],
              ['secret_key', saved ? '秘密密钥（留空保留）' : '秘密密钥'],
            ] as const
          ).map(([key, label]) => (
            <TextField
              key={key}
              id={key}
              label={label}
              {...form.register(key)}
              error={form.formState.errors[key]?.message}
              type={key.includes('key') ? 'password' : 'text'}
              autoComplete='off'
            />
          ))}
          <details className='space-y-4'>
            <summary className='cursor-pointer text-sm font-medium'>
              高级设置
            </summary>
            <FieldGroup>
              <TextField
                id='prefix'
                label='文件前缀'
                {...form.register('prefix')}
                error={form.formState.errors.prefix?.message}
              />
              <TextField
                id='public_url'
                label='CDN 根地址（可选）'
                {...form.register('public_url')}
                error={form.formState.errors.public_url?.message}
              />
            </FieldGroup>
          </details>
          {(
            [
              ['path_style', '使用路径形式访问 Bucket'],
              ['enabled', '启用存储'],
              ['is_default', '设为默认存储'],
            ] as const
          ).map(([key, label]) => (
            <Field key={key} orientation='horizontal'>
              <Checkbox
                id={key}
                checked={options[key]}
                onCheckedChange={(value) => form.setValue(key, value === true)}
              />
              <FieldLabel htmlFor={key}>{label}</FieldLabel>
            </Field>
          ))}
        </FieldGroup>
        {mutation.isError && <RequestError error={mutation.error} />}
        <Button disabled={mutation.isPending} type='submit'>
          {mutation.isPending ? '保存中…' : '保存存储'}
        </Button>
      </form>
    </Editor>
  )
}
