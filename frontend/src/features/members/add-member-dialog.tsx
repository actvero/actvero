import { useEffect, useRef } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
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
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { roleOptions } from './labels'

const schema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, '请输入姓名')
      .max(100, '姓名最多 100 个字符'),
    email: z.email('请输入有效邮箱'),
    role: z.enum(['member', 'administrator']),
    password: z
      .string()
      .min(12, '初始密码至少 12 个字符')
      .max(128, '初始密码最多 128 个字符'),
    confirmation: z.string(),
  })
  .refine((value) => value.password === value.confirmation, {
    path: ['confirmation'],
    message: '两次输入的密码不一致',
  })

export function AddMemberDialog({
  onClose,
  returnFocus,
  onCreated,
  path,
}: {
  onClose: () => void
  returnFocus: () => void
  onCreated: () => void
  path: string
}) {
  const { csrf } = useOrganization()
  const client = useQueryClient()
  const request = useRef<{ key: string; id: string } | null>(null)
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      email: '',
      role: 'member',
      password: '',
      confirmation: '',
    },
  })
  const creation = useMutation({
    mutationFn: () => {
      const value = schema.parse(form.getValues())
      // Only non-secret fields participate in the retry identity.
      const key = JSON.stringify([
        value.name,
        value.email.toLowerCase(),
        value.role,
      ])
      if (request.current?.key !== key)
        request.current = { key, id: crypto.randomUUID() }
      return api<Schema['MemberCreated']>(
        path + '/members',
        'POST',
        {
          request_id: request.current.id,
          name: value.name,
          email: value.email,
          role: value.role,
          password: value.password,
        },
        csrf
      )
    },
    onSuccess: async (result) => {
      form.reset()
      await client.invalidateQueries({ queryKey: ['organization'] })
      toast.success(
        result.initial_password_reused
          ? '成员已添加，初始密码沿用首次提交的值，请通知对方首次登录后修改。'
          : '成员已添加，请将登录邮箱和初始密码交给对方，首次登录需修改密码。'
      )
      onCreated()
      onClose()
    },
  })
  const resetMutation = creation.reset
  useEffect(() => () => resetMutation(), [resetMutation])
  function close() {
    if (creation.isPending) return
    form.reset()
    creation.reset()
    onClose()
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md'
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          returnFocus()
        }}
        onPointerDownOutside={(event) => {
          if (form.formState.isDirty || creation.isPending)
            event.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>添加成员</DialogTitle>
          <DialogDescription>
            直接创建账号并加入当前组织，无需发送邀请邮件。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            id='add-member'
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit(() => creation.mutate())}
          >
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>姓名</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      autoComplete='off'
                      maxLength={100}
                      disabled={creation.isPending}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='email'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>邮箱</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      type='email'
                      autoComplete='off'
                      placeholder='name@example.com'
                      disabled={creation.isPending}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='role'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>角色</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={creation.isPending}
                  >
                    <FormControl>
                      <SelectTrigger className='w-full'>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectGroup>
                        {roleOptions.map((role) => (
                          <SelectItem key={role.value} value={role.value}>
                            {role.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='password'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>初始密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      {...field}
                      autoComplete='new-password'
                      disabled={creation.isPending}
                    />
                  </FormControl>
                  <FormDescription>
                    至少 12 个字符，成员首次登录时需要修改。
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='confirmation'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>确认初始密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      {...field}
                      autoComplete='new-password'
                      disabled={creation.isPending}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {creation.isError && <RequestError error={creation.error} />}
          </form>
        </Form>
        <DialogFooter>
          <Button
            variant='outline'
            disabled={creation.isPending}
            onClick={close}
          >
            取消
          </Button>
          <Button type='submit' form='add-member' disabled={creation.isPending}>
            {creation.isPending ? '正在添加…' : '添加成员'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
