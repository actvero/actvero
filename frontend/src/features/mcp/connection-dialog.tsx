import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { toast } from 'sonner'
import { type Schema } from '@/lib/api'
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
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { useReturnFocus, useMcp, type Service } from './shared'

export function ConnectionDialog({
  service,
  close,
  returnFocus,
  memberMode = false,
}: {
  service: Service
  returnFocus?: () => void
  close: () => void
  memberMode?: boolean
}) {
  const restoreFocus = useReturnFocus(returnFocus)
  const { write, invalidate, discoverSaved } = useMcp()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const form = useForm({
    resolver: zodResolver(
      z.object({
        values: z.record(z.string(), z.string().min(1, '请输入凭据')),
      })
    ),
    defaultValues: {
      values: Object.fromEntries(
        (service.credential_fields ?? []).map((f) => [f.key, ''])
      ),
    },
  })
  async function action(kind: 'save' | 'oauth' | 'disconnect') {
    setPending(true)
    setError(null)
    try {
      if (kind === 'oauth') {
        const r = await write<Schema['McpAuthorizationUrl']>(
          `/services/${service.id}/oauth`,
          'POST'
        )
        window.location.assign(r.url)
        return
      }
      await write(
        `/services/${service.id}/connection`,
        kind === 'save' ? 'PUT' : 'DELETE',
        kind === 'save' ? form.getValues() : undefined
      )
      form.reset()
      if (kind === 'save') {
        void discoverSaved([{ ...service, configured: true }])
      } else {
        await invalidate()
        toast.success('已断开平台连接')
      }
      close()
    } catch (e) {
      setError(e)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !pending) close()
      }}
    >
      <DialogContent
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto'
        onCloseAutoFocus={restoreFocus}
        onPointerDownOutside={(e) => {
          if (form.formState.isDirty || pending) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {memberMode
              ? '配置个人凭据'
              : service.auth_mode === 'organization'
                ? '组织凭据'
                : '我的测试连接'}{' '}
            · {service.name}
          </DialogTitle>
          <DialogDescription>
            {memberMode
              ? '凭据仅保存给当前账号，用于验证你自己的业务连接。'
              : service.auth_mode === 'organization'
                ? '所有获授权成员使用此组织服务账号。'
                : '仅用于当前账号。其他成员须在自己的连接中授权。'}
            {service.configured ? ' 已有凭据不会回显，保存将完整替换。' : ''}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit(() => action('save'))}
          >
            {service.auth_mode === 'oauth' ? (
              <Button
                type='button'
                onClick={() => void action('oauth')}
                disabled={pending}
              >
                前往授权
              </Button>
            ) : (
              (service.credential_fields ?? []).map((f) => (
                <FormField
                  key={f.key}
                  control={form.control}
                  name={`values.${f.key}`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{f.label}</FormLabel>
                      <FormControl>
                        <PasswordInput
                          {...field}
                          autoComplete='new-password'
                          placeholder={
                            f.bearer ? '只填凭据，不用填写 Bearer' : ''
                          }
                          disabled={pending}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))
            )}
            {!!error && <RequestError error={error} />}
            <DialogFooter>
              {service.configured && (
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => void action('disconnect')}
                  disabled={pending}
                >
                  断开连接
                </Button>
              )}
              <Button
                type='button'
                variant='outline'
                onClick={close}
                disabled={pending}
              >
                取消
              </Button>
              {service.auth_mode !== 'oauth' && (
                <Button disabled={pending}>保存凭据</Button>
              )}
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
