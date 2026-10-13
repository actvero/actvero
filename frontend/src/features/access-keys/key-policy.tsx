import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { RequestError } from '@/components/request-state'

const schema = z.object({
  enabled: z.boolean(),
  maxDays: z
    .string()
    .refine(
      (v) =>
        v === '' || (/^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 3650),
      '填写 1–3650 天，或留空'
    ),
})
export function KeyPolicyEditor({
  rules,
  csrf,
  onClose,
  onSaved,
  restore,
}: {
  rules: Schema['KeyPolicyView']
  csrf: string
  onClose: () => void
  onSaved: () => void
  restore: () => void
}) {
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      enabled: rules.enabled,
      maxDays: rules.max_days ? String(rules.max_days) : '',
    },
  })
  const [error, setError] = useState<unknown>(null)
  const busy = form.formState.isSubmitting
  async function save(v: z.infer<typeof schema>) {
    setError(null)
    try {
      await api(
        '/access-keys/policy',
        'PUT',
        {
          version: rules.version,
          enabled: v.enabled,
          max_days: v.maxDays ? Number(v.maxDays) : null,
        },
        csrf
      )
      onSaved()
      onClose()
      toast.success('密钥规则已保存')
    } catch (e) {
      setError(e)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !busy) onClose()
      }}
    >
      <DialogContent
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
      >
        <DialogHeader>
          <DialogTitle>组织密钥规则</DialogTitle>
          <DialogDescription>规则同时约束新建和已有密钥。</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(save)}
            className='flex flex-col gap-4'
          >
            <FormField
              control={form.control}
              name='enabled'
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-4'>
                  <FormLabel>允许个人访问密钥</FormLabel>
                  <FormControl>
                    <Switch
                      disabled={busy}
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='maxDays'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>最长有效期（天）</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      disabled={busy}
                      inputMode='numeric'
                      placeholder='不额外限制'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {error != null && <RequestError error={error} />}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                disabled={busy}
                onClick={onClose}
              >
                取消
              </Button>
              <Button type='submit' disabled={busy}>
                {busy ? '正在保存…' : '保存规则'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
