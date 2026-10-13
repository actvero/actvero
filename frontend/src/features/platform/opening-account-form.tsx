import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api } from '@/lib/api'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'

const schema = z.object({
  name: z.string().trim().min(1, '请填写管理员姓名').max(100),
  email: z.email('请填写有效邮箱'),
  password: z
    .string()
    .min(12, '密码需要 12–128 个字符')
    .max(128, '密码需要 12–128 个字符'),
})

export function OpeningAccountForm({
  invitation,
  flow,
  csrf,
  recipient,
  login,
}: {
  invitation: boolean
  flow: string
  csrf: string
  recipient?: string | null
  login: string
}) {
  const [tab, setTab] = useState('register')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { name: '', email: recipient ?? '', password: '' },
  })
  async function register(values: z.infer<typeof schema>) {
    setError(null)
    setPending(true)
    try {
      // Credentials stay outside Query's mutation cache and are cleared on every outcome.
      await api(
        `/organization-onboarding/register?flow=${flow}`,
        'POST',
        { ...values, invitation },
        csrf
      )
      window.location.assign(login)
    } catch (failure) {
      setError(failure)
    } finally {
      form.resetField('password')
      setPending(false)
    }
  }
  return (
    <Tabs
      value={tab}
      onValueChange={(value) => {
        form.resetField('password')
        setError(null)
        setTab(value)
      }}
    >
      <TabsList className='w-full'>
        <TabsTrigger value='register' disabled={pending}>
          注册新账号
        </TabsTrigger>
        <TabsTrigger value='login' disabled={pending}>
          使用已有账号
        </TabsTrigger>
      </TabsList>
      <TabsContent value='register'>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit(register)}
          >
            {(['name', 'email'] as const).map((name) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {name === 'name' ? '管理员姓名' : '邮箱'}
                    </FormLabel>
                    <FormControl>
                      <Input
                        type={name === 'email' ? 'email' : 'text'}
                        autoComplete={name}
                        readOnly={name === 'email' && !!recipient}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
            <FormField
              control={form.control}
              name='password'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>密码</FormLabel>
                  <FormControl>
                    <PasswordInput autoComplete='new-password' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {error ? <RequestError error={error} /> : null}
            <Button disabled={pending}>
              {pending ? '创建中…' : '创建账号并继续'}
            </Button>
            {error ? (
              <Button variant='link' asChild>
                <a href={login}>登录已有账号</a>
              </Button>
            ) : null}
          </form>
        </Form>
      </TabsContent>
      <TabsContent value='login'>
        <Button className='w-full' asChild>
          <a href={login}>登录并继续</a>
        </Button>
      </TabsContent>
    </Tabs>
  )
}
