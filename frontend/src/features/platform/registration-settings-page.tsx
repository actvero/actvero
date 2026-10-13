import { z } from 'zod'
import { useForm, useFormState } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'

const schema = z.object({
  mode: z.enum(['invite', 'approval', 'self_service']),
  invitation_verify_email: z.boolean(),
})
export function RegistrationSettingsPage() {
  const query = useQuery({
    queryKey: ['platform', 'registration'],
    queryFn: () =>
      api<Schema['RegistrationPolicyView']>('/platform/registration'),
  })
  return (
    <PageShell title='注册与开通'>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <PolicyForm key={JSON.stringify(query.data)} value={query.data} />
      )}
    </PageShell>
  )
}
function PolicyForm({ value }: { value: Schema['RegistrationPolicyView'] }) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      mode: value.mode ?? 'invite',
      invitation_verify_email: value.invitation_verify_email ?? false,
    },
  })
  const { isDirty } = useFormState({ control: form.control })
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      api('/platform/registration', 'PUT', values, session?.csrf),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['platform', 'registration'] })
      await client.invalidateQueries({ queryKey: ['session'] })
      toast.success('开通设置已保存')
    },
  })
  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((values) => save.mutate(values))}>
        <Card className='max-w-3xl'>
          <CardHeader>
            <CardTitle>组织开通方式</CardTitle>
          </CardHeader>
          <CardContent className='flex flex-col gap-6'>
            <FormField
              control={form.control}
              name='mode'
              render={({ field }) => (
                <FormItem>
                  <FormLabel className='sr-only'>开通方式</FormLabel>
                  <FormControl>
                    <RadioGroup
                      value={field.value}
                      onValueChange={field.onChange}
                      className='gap-4'
                    >
                      {(
                        [
                          ['invite', '仅邀请开通'],
                          ['approval', '申请审核开通'],
                          ['self_service', '自助开通'],
                        ] as const
                      ).map(([mode, label]) => (
                        <FormItem
                          key={mode}
                          className='flex items-center gap-3'
                        >
                          <FormControl>
                            <RadioGroupItem
                              value={mode}
                              disabled={
                                !value.mail_enabled && mode !== 'invite'
                              }
                            />
                          </FormControl>
                          <FormLabel>{label}</FormLabel>
                        </FormItem>
                      ))}
                    </RadioGroup>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='invitation_verify_email'
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-4'>
                  <FormLabel>邀请开通时验证邮箱</FormLabel>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={!value.mail_enabled && !field.value}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            {!value.mail_enabled && (
              <p className='text-sm text-muted-foreground'>
                公开开通和邮箱验证需要先配置
                <Button variant='link' asChild>
                  <Link to='/platform/settings/mail'>邮件服务</Link>
                </Button>
              </p>
            )}
            {value.mode !== 'invite' && (
              <Button variant='link' asChild className='self-start'>
                <Link to='/organization-onboarding'>查看开通页面</Link>
              </Button>
            )}
            {save.isError && <RequestError error={save.error} />}
          </CardContent>
          <CardFooter className='justify-end'>
            <Button disabled={!isDirty || save.isPending}>
              {save.isPending ? '保存中…' : '保存'}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </Form>
  )
}
