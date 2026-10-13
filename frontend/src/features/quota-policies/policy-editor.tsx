import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
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
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { MemberPicker } from '@/components/member-picker'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  policyInput,
  policySchema,
  values,
  type Policy,
  type PolicyValues,
} from './policy-form'
import { RuleFields } from './rule-fields'

export function PolicyEditor({
  policy,
  isDefault,
  close,
  saved,
  restoreFocus,
}: {
  policy?: Policy
  isDefault: boolean
  close: () => void
  saved: () => void
  restoreFocus?: () => void
}) {
  const { csrf } = useOrganization()
  const form = useForm<PolicyValues>({
    resolver: zodResolver(policySchema),
    defaultValues: values(policy, isDefault),
  })
  const [error, setError] = useState<unknown>(null)
  const pending = form.formState.isSubmitting
  async function submit(data: PolicyValues) {
    if (!isDefault && Number(data.priority) === 0) {
      form.setError('priority', { message: '普通策略的优先级需大于 0' })
      return
    }
    setError(null)
    try {
      await api<Policy>(
        policy ? '/quota/policies/' + policy.id : '/quota/policies',
        policy ? 'PUT' : 'POST',
        {
          ...policyInput(data),
          ...(policy ? { version: policy.version } : {}),
        },
        csrf
      )
      saved()
    } catch (e) {
      setError(e)
    }
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open && !pending) close()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-3xl'
        aria-describedby={undefined}
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          form.setFocus('name')
        }}
        onCloseAutoFocus={
          restoreFocus
            ? (e) => {
                e.preventDefault()
                restoreFocus()
              }
            : undefined
        }
      >
        <SheetHeader className='shrink-0 px-4 pr-12 sm:px-6'>
          <SheetTitle>
            {policy ? '编辑策略' : isDefault ? '设置默认策略' : '新建策略'}
          </SheetTitle>
        </SheetHeader>
        <Separator />
        <Form {...form}>
          <form
            className='flex min-h-0 flex-1 flex-col'
            onSubmit={(e) => void form.handleSubmit(submit)(e)}
          >
            <fieldset
              disabled={pending}
              className='flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4 sm:p-6'
            >
              <div className='grid gap-4 sm:grid-cols-2'>
                <FormField
                  control={form.control}
                  name='name'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>名称</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          maxLength={100}
                          placeholder='策略名称'
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name='priority'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>优先级</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          inputMode='numeric'
                          readOnly={isDefault}
                          placeholder='数值越大，优先级越高'
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <RuleFields disabled={pending} />
              <Separator />
              {isDefault ? (
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>适用成员</span>
                  <Badge variant='secondary'>全部成员</Badge>
                  <span className='text-sm text-muted-foreground'>
                    包含以后加入的成员
                  </span>
                </div>
              ) : (
                <FormField
                  control={form.control}
                  name='member_ids'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>适用成员</FormLabel>
                      <FormControl>
                        <MemberPicker
                          value={field.value}
                          onChange={field.onChange}
                          includeAdministrators
                          selectionLabel='适用成员'
                          disabled={pending}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </fieldset>
            <Separator />
            <SheetFooter className='shrink-0 flex-row flex-wrap justify-end px-4 sm:px-6'>
              {!!error && (
                <div className='w-full'>
                  <RequestError error={error} />
                </div>
              )}
              <Button
                type='button'
                variant='outline'
                onClick={close}
                disabled={pending}
              >
                取消
              </Button>
              <Button disabled={pending}>{pending ? '保存中…' : '保存'}</Button>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  )
}
