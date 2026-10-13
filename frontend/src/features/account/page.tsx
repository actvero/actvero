import { useEffect } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AvatarEditor } from '@/components/avatar-editor'
import { PageShell } from '@/components/layout/page-shell'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { roleName } from '@/features/members/labels'
import { uploadAvatar } from './api'
import { DeviceSettings } from './devices'

const profileSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, '请输入姓名')
    .max(100, '姓名最多 100 个字符')
    .refine((value) => !/[\p{Cc}]/u.test(value), '姓名不能包含控制字符'),
})

export function AccountPage() {
  const { user, organization, csrf, session } = useOrganization()
  const queryClient = useQueryClient()
  const { tab, password } = useSearch({ from: '/_authenticated/account' })
  const navigate = useNavigate({ from: '/account' })
  const form = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: { name: user.name },
  })
  useEffect(() => {
    if (!form.formState.isDirty) form.reset({ name: user.name })
  }, [form, user.name])
  async function refresh(updated: Schema['UserView']) {
    queryClient.setQueryData<Schema['SessionView']>(['session'], (current) =>
      current ? { ...current, user: updated } : current
    )
    await queryClient.invalidateQueries({ queryKey: ['organization'] })
  }
  const profile = useMutation({
    mutationFn: (values: z.infer<typeof profileSchema>) =>
      api<Schema['UserView']>('/account/profile', 'PATCH', values, csrf),
    onSuccess: async (updated) => {
      form.reset({ name: updated.name })
      await refresh(updated)
      toast.success('姓名已保存')
    },
  })
  const avatar = useMutation({
    mutationFn: (file: File | null) =>
      file
        ? uploadAvatar(file, csrf)
        : api<Schema['UserView']>('/account/avatar', 'DELETE', undefined, csrf),
    onSuccess: async (updated, file) => {
      await refresh(updated)
      toast.success(file ? '头像已更新' : '头像已移除')
    },
  })
  const changePassword = useMutation({
    mutationFn: () =>
      api<Schema['PasswordAction']>('/auth/password', 'POST', undefined, csrf),
    onSuccess: (result) => window.location.assign(result.url),
  })
  return (
    <PageShell title='个人设置'>
      <div
        className={cn(
          'w-full min-w-0',
          tab === 'devices' ? 'max-w-4xl' : 'max-w-2xl'
        )}
      >
        <Tabs
          value={tab ?? 'profile'}
          onValueChange={(value) =>
            void navigate({
              search: {
                tab:
                  value === 'devices'
                    ? 'devices'
                    : value === 'security'
                      ? 'security'
                      : 'profile',
              },
              replace: true,
            })
          }
          className='gap-6'
        >
          <TabsList aria-label='个人设置' className='h-auto flex-wrap'>
            <TabsTrigger value='profile'>个人信息</TabsTrigger>
            <TabsTrigger value='security'>账号安全</TabsTrigger>
            <TabsTrigger value='devices'>登录设备</TabsTrigger>
          </TabsList>
          <TabsContent value='profile'>
            <Card>
              <CardHeader>
                <CardTitle>个人信息</CardTitle>
              </CardHeader>
              <CardContent className='flex flex-col gap-6'>
                <Form {...form}>
                  <form
                    onSubmit={form.handleSubmit((values) =>
                      profile.mutate(values)
                    )}
                    className='flex flex-col gap-5'
                  >
                    <div className='flex items-center gap-5'>
                      <AvatarEditor
                        value={user.avatar_url}
                        fallback={Array.from(user.name.trim() || '用户')
                          .slice(-2)
                          .join('')}
                        disabled={avatar.isPending || profile.isPending}
                        onChange={async (file) => {
                          await avatar.mutateAsync(file)
                        }}
                      />
                      <FormField
                        control={form.control}
                        name='name'
                        render={({ field }) => (
                          <FormItem className='min-w-0 flex-1'>
                            <FormLabel>姓名</FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                autoComplete='name'
                                maxLength={100}
                                disabled={profile.isPending || avatar.isPending}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>
                    <div className='grid gap-2'>
                      <Label htmlFor='account-email'>邮箱</Label>
                      <Input
                        id='account-email'
                        value={user.email ?? '未设置'}
                        readOnly
                        autoComplete='email'
                      />
                    </div>
                    <p className='text-sm text-muted-foreground'>
                      {organization.name} · {roleName(organization.role)}
                    </p>
                    {profile.isError && <RequestError error={profile.error} />}
                    <div className='flex justify-end'>
                      <Button
                        type='submit'
                        disabled={
                          !form.formState.isDirty ||
                          profile.isPending ||
                          avatar.isPending
                        }
                      >
                        {profile.isPending ? '正在保存…' : '保存更改'}
                      </Button>
                    </div>
                  </form>
                </Form>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value='security'>
            <Card>
              <CardHeader>
                <CardTitle>登录与安全</CardTitle>
                <CardDescription>保护你的账号与登录凭据。</CardDescription>
              </CardHeader>
              <CardContent className='flex flex-col gap-5'>
                {password && (
                  <p role='status' className='text-sm text-muted-foreground'>
                    {password === 'cancelled'
                      ? '已取消修改密码。'
                      : '密码修改流程未完成，请重试。'}
                  </p>
                )}
                <div className='flex flex-wrap items-center justify-between gap-4'>
                  <div className='grid gap-1'>
                    <p className='text-sm font-medium'>登录密码</p>
                    <p className='text-sm text-muted-foreground'>
                      修改前可能需要验证当前密码。
                    </p>
                  </div>
                  <Button
                    variant='outline'
                    disabled={changePassword.isPending}
                    onClick={() => changePassword.mutate()}
                  >
                    {changePassword.isPending ? '正在跳转…' : '修改密码'}
                  </Button>
                </div>
                {changePassword.isError && (
                  <RequestError error={changePassword.error} />
                )}
                <Separator />
                <div className='flex flex-wrap items-center justify-between gap-4'>
                  <div className='grid gap-1'>
                    <p className='text-sm font-medium'>更多安全设置</p>
                    <p className='text-sm text-muted-foreground'>
                      管理双重验证与身份服务登录会话。
                    </p>
                  </div>
                  {session.account_url && (
                    <Button variant='ghost' asChild>
                      <a
                        href={session.account_url}
                        target='_blank'
                        rel='noreferrer'
                      >
                        前往管理
                      </a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value='devices'>
            <DeviceSettings userId={user.id} csrf={csrf} />
          </TabsContent>
        </Tabs>
      </div>
    </PageShell>
  )
}
