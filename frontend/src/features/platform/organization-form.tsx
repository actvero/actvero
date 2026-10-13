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
  FormField,
  FormItem,
  FormControl,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { AccountCard } from '@/components/account-card'
import { RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'

const schema = z.object({
  organization_name: z.string().trim().min(2, '组织名称至少 2 个字符').max(60),
  active: z.boolean(),
})
export function OrganizationForm({
  organization,
  onClose,
}: {
  organization: Schema['PlatformOrganization'] | null
  onClose: () => void
}) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      organization_name: organization?.name ?? '',
      active: organization?.active ?? true,
    },
  })
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      api(
        organization
          ? `/platform/organizations/${organization.id}`
          : '/platform/organizations',
        organization ? 'PUT' : 'POST',
        organization
          ? values
          : { ...values, confirmed_user_id: session?.user?.id },
        session?.csrf
      ),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ['platform', 'organizations'],
      })
      await client.invalidateQueries({ queryKey: ['session'] })
      toast.success(organization ? '组织已更新' : '组织已创建')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{organization ? '编辑组织' : '创建组织'}</DialogTitle>
          <DialogDescription>
            {organization
              ? '暂停后，组织成员和客户端将无法访问。'
              : '当前账号将成为组织管理员。'}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit((values) => save.mutate(values))}
          >
            {!organization && session?.user && (
              <div className='flex flex-col gap-2'>
                <p className='text-sm font-medium'>管理员账号</p>
                <AccountCard user={session.user} wrapDetails />
              </div>
            )}
            <FormField
              control={form.control}
              name='organization_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>组织名称</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {organization && (
              <FormField
                control={form.control}
                name='active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between'>
                    <FormLabel>启用组织</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            )}
            {save.isError && <RequestError error={save.error} />}
            <DialogFooter>
              <Button
                variant='outline'
                type='button'
                disabled={save.isPending}
                onClick={onClose}
              >
                取消
              </Button>
              <Button disabled={save.isPending}>
                {save.isPending ? '保存中…' : organization ? '保存' : '创建'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
