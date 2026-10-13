import { useId, useState, type ReactNode } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormDescription,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'

const mailSchema = z.object({
  enabled: z.boolean(),
  host: z
    .string()
    .trim()
    .min(1, '请输入 SMTP 主机')
    .max(253)
    .regex(/^[^\s/\\:@?#]+$/, '请输入主机名，不含协议和端口'),
  port: z.number().int().min(1).max(65535),
  security: z.enum(['tls', 'starttls', 'none']),
  sender: z.email('请输入有效的发件邮箱'),
  username: z.string().trim().max(320),
  password: z.string().max(1000),
})

export function MailSettingsForm({
  saved,
  onSaved,
  action,
}: {
  saved: Schema['MailSettingsView']
  onSaved?: () => void
  action?: ReactNode
}) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const formId = useId()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>()
  const form = useForm<z.infer<typeof mailSchema>>({
    resolver: zodResolver(mailSchema),
    defaultValues: {
      enabled: saved.enabled,
      host: saved.host,
      port: saved.port,
      security: saved.security,
      sender: saved.sender,
      username: saved.username,
      password: '',
    },
  })
  return (
    <Form {...form}>
      <form
        id={formId}
        className='flex flex-col gap-4'
        onSubmit={form.handleSubmit(async (values) => {
          const changed =
            values.host.toLowerCase() !== saved.host.toLowerCase() ||
            values.port !== saved.port ||
            values.security !== saved.security ||
            values.username !== saved.username
          if (
            values.username &&
            !values.password &&
            (!saved.password_set || changed)
          ) {
            form.setError('password', {
              message: '请输入授权码；更换服务器、连接方式或账号后需重新填写。',
            })
            return
          }
          setPending(true)
          setError(undefined)
          try {
            const result = await api<Schema['MailSettingsView']>(
              '/platform/mail',
              'PUT',
              {
                ...values,
                password: values.password || null,
                clear_password: !values.username,
              },
              session?.csrf
            )
            client.setQueryData(['platform', 'mail'], result)
            form.reset({
              enabled: result.enabled,
              host: result.host,
              port: result.port,
              security: result.security,
              sender: result.sender,
              username: result.username,
              password: '',
            })
            await Promise.all([
              client.invalidateQueries({ queryKey: ['platform', 'settings'] }),
              client.invalidateQueries({ queryKey: ['session'] }),
            ])
            toast.success('邮件配置已保存')
            onSaved?.()
          } catch (cause) {
            setError(cause)
          } finally {
            form.resetField('password')
            setPending(false)
          }
        })}
      >
        <fieldset disabled={pending} className='flex min-w-0 flex-col gap-4'>
          <FormField
            control={form.control}
            name='enabled'
            render={({ field }) => (
              <FormItem className='flex items-center justify-between gap-4'>
                <div>
                  <FormLabel>启用邮件服务</FormLabel>
                </div>
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className='grid gap-4 sm:grid-cols-[minmax(0,1fr)_100px]'>
            <FormField
              control={form.control}
              name='host'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>SMTP 服务器</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder='smtp.example.com'
                      autoComplete='off'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='port'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>端口</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      type='number'
                      min={1}
                      max={65535}
                      onChange={(event) =>
                        field.onChange(event.target.valueAsNumber)
                      }
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
          <FormField
            control={form.control}
            name='security'
            render={({ field }) => (
              <FormItem>
                <FormLabel>连接加密</FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='tls'>SSL / TLS</SelectItem>
                      <SelectItem value='starttls'>STARTTLS</SelectItem>
                      <SelectItem value='none'>无加密</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='sender'
            render={({ field }) => (
              <FormItem>
                <FormLabel>发件邮箱</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    type='email'
                    placeholder='noreply@example.com'
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='username'
            render={({ field }) => (
              <FormItem>
                <FormLabel>登录账号（可选）</FormLabel>
                <FormControl>
                  <Input {...field} autoComplete='off' />
                </FormControl>
                <FormDescription>
                  通常为完整邮箱地址。免认证服务可留空。
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='password'
            render={({ field }) => (
              <FormItem>
                <FormLabel>授权码 / 密码</FormLabel>
                <FormControl>
                  <PasswordInput
                    {...field}
                    autoComplete='new-password'
                    placeholder={
                      saved.password_set
                        ? '已设置，留空保留'
                        : '输入邮箱服务商提供的授权码'
                    }
                  />
                </FormControl>
                <FormDescription>
                  QQ 等邮箱使用 SMTP 授权码，不填写网页登录密码。
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </fieldset>
        {error !== undefined && <RequestError error={error} />}
      </form>
      <div className='flex flex-wrap justify-end gap-3'>
        {action}
        <Button
          type='submit'
          form={formId}
          disabled={pending || !form.formState.isDirty}
        >
          {pending ? '保存中…' : '保存配置'}
        </Button>
      </div>
    </Form>
  )
}

const recipientSchema = z.object({ email: z.email('请输入有效的收件邮箱') })
export function MailTestForm({
  path = '/platform/mail/test',
  invitation = false,
}: {
  path?: string
  invitation?: boolean
}) {
  const { data: session } = useSession()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>()
  const [message, setMessage] = useState('')
  const form = useForm<z.infer<typeof recipientSchema>>({
    resolver: zodResolver(recipientSchema),
    defaultValues: { email: invitation ? '' : (session?.user?.email ?? '') },
  })
  return (
    <Form {...form}>
      <form
        className='flex flex-col gap-4'
        onSubmit={form.handleSubmit(async (values) => {
          setPending(true)
          setError(undefined)
          setMessage('')
          try {
            const result = await api<Schema['Message']>(
              path,
              'POST',
              values,
              session?.csrf
            )
            setMessage(result.message)
          } catch (cause) {
            setError(cause)
          } finally {
            setPending(false)
          }
        })}
      >
        <FormField
          control={form.control}
          name='email'
          render={({ field }) => (
            <FormItem>
              <FormLabel>收件邮箱</FormLabel>
              <FormControl>
                <Input {...field} type='email' disabled={pending} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {error !== undefined && <RequestError error={error} />}
        {message && (
          <p role='status' className='text-sm text-muted-foreground'>
            {message}
          </p>
        )}
        <div className='flex justify-end'>
          <Button type='submit' disabled={pending || Boolean(message)}>
            {pending ? '发送中…' : invitation ? '发送邀请邮件' : '发送测试邮件'}
          </Button>
        </div>
      </form>
    </Form>
  )
}
