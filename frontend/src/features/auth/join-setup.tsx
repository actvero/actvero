import { useState } from 'react'
import { z } from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
import { avatarDataUrl } from '@/lib/avatar-image'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { AvatarEditor } from '@/components/avatar-editor'
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { loginUrl } from './session'

const setupSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, '请填写姓名')
      .max(100, '姓名最多 100 个字符')
      .refine((value) => !/[\p{Cc}]/u.test(value), '请填写有效姓名'),
    password: z.string().min(12, '密码至少 12 个字符').max(128),
    confirm: z.string(),
  })
  .refine((value) => value.password === value.confirm, {
    message: '两次输入的密码不一致',
    path: ['confirm'],
  })

export function JoinSetup({
  invitation,
  csrf,
  refresh,
}: {
  invitation: Schema['InvitationPreview']
  csrf: string
  refresh: () => void
}) {
  const [avatar, setAvatar] = useState<string | null>(null)
  const form = useForm<z.infer<typeof setupSchema>>({
    resolver: zodResolver(setupSchema),
    defaultValues: { name: invitation.name ?? '', password: '', confirm: '' },
  })
  const name = useWatch({ control: form.control, name: 'name' })
  const register = useMutation({
    gcTime: 0,
    mutationFn: ({ name, password }: z.infer<typeof setupSchema>) =>
      api<Schema['SetupResult']>(
        '/invitations/setup',
        'POST',
        { name, password, avatar } satisfies Schema['InvitationSetup'],
        csrf
      ),
    onSuccess: () => {
      form.reset()
      window.location.assign(loginUrl('/console', true))
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) refresh()
    },
  })
  const busy = register.isPending || register.isSuccess

  return (
    <Form {...form}>
      <form
        className='flex flex-col gap-4'
        onSubmit={form.handleSubmit((values) => register.mutate(values))}
      >
        <div className='flex items-center gap-3'>
          <AvatarEditor
            value={avatar}
            fallback={Array.from(name.trim() || '成员')
              .slice(-2)
              .join('')}
            disabled={busy}
            onChange={async (file) =>
              setAvatar(file ? await avatarDataUrl(file) : null)
            }
          />
          <span className='text-sm text-muted-foreground'>头像（选填）</span>
        </div>
        <FormField
          control={form.control}
          name='name'
          render={({ field }) => (
            <FormItem>
              <FormLabel>姓名</FormLabel>
              <FormControl>
                <Input
                  autoComplete='name'
                  maxLength={100}
                  disabled={busy}
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {(['password', 'confirm'] as const).map((name) => (
          <FormField
            key={name}
            control={form.control}
            name={name}
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  {name === 'password' ? '设置密码' : '确认密码'}
                </FormLabel>
                <FormControl>
                  <PasswordInput
                    autoComplete='new-password'
                    maxLength={128}
                    placeholder={
                      name === 'password' ? '至少 12 个字符' : undefined
                    }
                    disabled={busy}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
        {register.error && <RequestError error={register.error} />}
        <Button type='submit' disabled={busy}>
          {register.isSuccess
            ? '已加入，正在前往登录…'
            : register.isPending
              ? '正在设置账号…'
              : '完成设置并加入'}
        </Button>
        <p className='text-sm text-muted-foreground'>
          完成后，用刚设置的密码登录工作空间。
        </p>
      </form>
    </Form>
  )
}
