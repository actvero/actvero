import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { Navigate } from '@tanstack/react-router'
import { api, type Schema } from '@/lib/api'
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
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { useBranding } from '@/features/branding/data'
import { AuthLayout } from './auth-layout'
import { loginUrl, useSession } from './session'

const setupSchema = z
  .object({
    organization_name: z.string().trim().max(60),
    name: z.string().trim().min(1, '请填写姓名').max(100),
    email: z.email('请填写有效邮箱'),
    password: z.string().min(12, '密码至少 12 个字符').max(128),
    confirm: z.string(),
  })
  .refine((value) => value.password === value.confirm, {
    message: '两次输入的密码不一致',
    path: ['confirm'],
  })
export function SetupPage() {
  const brand = useBranding()
  const { data: session, refetch } = useSession()
  const form = useForm({
    resolver: zodResolver(setupSchema),
    defaultValues: {
      organization_name: '',
      name: '',
      email: '',
      password: '',
      confirm: '',
    },
  })
  const register = useMutation({
    mutationFn: ({
      confirm: _confirm,
      ...values
    }: z.infer<typeof setupSchema>) =>
      api<Schema['Message']>('/setup/register', 'POST', values, session?.csrf),
    onSuccess: () => {
      form.reset()
      window.location.replace(loginUrl('/console', true))
    },
  })
  const isSaas = session?.platform_edition === 'saas'
  if (session?.setup_complete) return <Navigate to='/console' replace />
  if (session?.setup_account_created) return <Navigate to='/login' replace />
  return (
    <AuthLayout
      title={`初始化 ${brand.name}`}
      description={
        isSaas
          ? '创建第一个平台运营人员，开始管理组织。'
          : '创建组织和第一名管理员，开始使用。'
      }
    >
      <Form {...form}>
        <form
          className='flex flex-col gap-4'
          onSubmit={form.handleSubmit((value) => register.mutate(value))}
        >
          {(['organization_name', 'name', 'email'] as const)
            .filter((name) => name !== 'organization_name' || !isSaas)
            .map((name) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {
                        {
                          organization_name: '组织名称',
                          name: '管理员姓名',
                          email: '邮箱',
                        }[name]
                      }
                    </FormLabel>
                    <FormControl>
                      <Input
                        type={name === 'email' ? 'email' : 'text'}
                        autoComplete={
                          name === 'email'
                            ? 'email'
                            : name === 'name'
                              ? 'name'
                              : 'organization'
                        }
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          {(['password', 'confirm'] as const).map((name) => (
            <FormField
              key={name}
              control={form.control}
              name={name}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {name === 'password' ? '密码' : '确认密码'}
                  </FormLabel>
                  <FormControl>
                    <PasswordInput autoComplete='new-password' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
          <p className='text-sm text-muted-foreground'>
            密码至少 12 个字符。
            {isSaas
              ? ' 创建后将成为平台运营人员，再由平台后台创建组织。'
              : ' 创建后将跳转到登录页。'}
          </p>
          {register.isError && <RequestError error={register.error} />}
          {register.isError && (
            <Button
              type='button'
              variant='outline'
              onClick={() => void refetch()}
            >
              刷新初始化状态
            </Button>
          )}
          <Button disabled={register.isPending || register.isSuccess}>
            {register.isPending
              ? '正在创建…'
              : register.isSuccess
                ? '正在跳转登录…'
                : '创建管理员账号'}
          </Button>
        </form>
      </Form>
    </AuthLayout>
  )
}
