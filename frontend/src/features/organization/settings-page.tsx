import { useState } from 'react'
import { z } from 'zod'
import { useForm, useFormState } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, dateTime, messageOf, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(2, '组织名称至少 2 个字符')
    .max(60, '最多 60 个字符'),
})

export function OrganizationSettingsPage() {
  const { organization } = useOrganization()
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, 'settings'],
    queryFn: () =>
      api<Schema['OrganizationSettings']>(
        `/enterprises/${organization.tenant_id}/settings`
      ),
  })
  return (
    <PageShell title='组织设置'>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <OrganizationSettingsForm
          key={organization.tenant_id}
          initial={query.data}
        />
      )}
    </PageShell>
  )
}

function OrganizationSettingsForm({
  initial,
}: {
  initial: Schema['OrganizationSettings']
}) {
  const { csrf } = useOrganization()
  const client = useQueryClient()
  const [saved, setSaved] = useState(initial)
  const form = useForm({
    resolver: zodResolver(schema),
    mode: 'onChange',
    defaultValues: { name: saved.name },
  })
  const { errors, isDirty, isValid } = useFormState({ control: form.control })
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      api<Schema['OrganizationSettings']>(
        `/enterprises/${saved.id}/settings`,
        'PUT',
        { ...values, expected_name: saved.name },
        csrf
      ),
    onSuccess: async (value) => {
      setSaved(value)
      form.reset({ name: value.name })
      client.setQueryData(['organization', value.id, 'settings'], value)
      await client.invalidateQueries({ queryKey: ['session'] })
      toast.success('组织设置已保存')
    },
  })
  async function reload() {
    try {
      const value = await client.fetchQuery({
        queryKey: ['organization', saved.id, 'settings'],
        queryFn: () =>
          api<Schema['OrganizationSettings']>(
            `/enterprises/${saved.id}/settings`
          ),
        staleTime: 0,
      })
      setSaved(value)
      form.reset({ name: value.name })
      save.reset()
    } catch (error) {
      toast.error(messageOf(error))
    }
  }
  return (
    <form
      className='w-full max-w-3xl'
      onSubmit={form.handleSubmit((values) => save.mutate(values))}
    >
      <Card>
        <CardHeader>
          <CardTitle>基本信息</CardTitle>
          <CardDescription>组织名称会显示在管理后台和桌面端。</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field data-invalid={Boolean(errors.name)}>
              <FieldLabel htmlFor='organization-name'>组织名称</FieldLabel>
              <Input
                id='organization-name'
                maxLength={60}
                autoComplete='organization'
                aria-invalid={Boolean(errors.name)}
                aria-describedby={
                  errors.name ? 'organization-name-error' : undefined
                }
                disabled={save.isPending}
                {...form.register('name')}
              />
              {errors.name && (
                <FieldError
                  id='organization-name-error'
                  errors={[errors.name]}
                />
              )}
            </Field>
            <Field>
              <FieldLabel htmlFor='organization-id'>组织 ID</FieldLabel>
              <Input id='organization-id' value={saved.id} readOnly />
            </Field>
            <Field>
              <FieldLabel htmlFor='organization-created-at'>
                创建时间
              </FieldLabel>
              <Input
                id='organization-created-at'
                value={dateTime(saved.created_at)}
                readOnly
              />
            </Field>
            {save.isError && (
              <RequestError error={save.error} retry={() => void reload()} />
            )}
          </FieldGroup>
        </CardContent>
        <CardFooter className='justify-end gap-2'>
          <Button
            type='button'
            variant='outline'
            disabled={!isDirty || save.isPending}
            onClick={() => {
              form.reset({ name: saved.name })
              save.reset()
            }}
          >
            取消更改
          </Button>
          <Button disabled={!isDirty || !isValid || save.isPending}>
            {save.isPending ? '保存中…' : '保存'}
          </Button>
        </CardFooter>
      </Card>
    </form>
  )
}
