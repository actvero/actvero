import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FieldGroup } from '@/components/ui/field'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
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
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
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
  const mode = useWatch({ control: form.control, name: 'mode' })
  const pending = form.formState.isSubmitting
  async function submit(data: PolicyValues) {
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
              <FieldGroup>
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
                  name='mode'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>额度方式</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className='w-full'>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value='limited'>周期限额</SelectItem>
                            <SelectItem value='unlimited'>不限额度</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </FieldGroup>
              {mode === 'limited' ? (
                <RuleFields disabled={pending} />
              ) : (
                <p className='text-sm text-muted-foreground'>
                  不设置成员积分上限，用量与成本仍正常记录。模型访问权限保持独立。
                </p>
              )}
              <Separator />
              {isDefault ? (
                <div className='flex flex-wrap items-center gap-2'>
                  <Badge variant='secondary'>组织默认</Badge>
                  <span className='text-sm text-muted-foreground'>
                    未指定策略的成员自动继承，包含以后加入的成员。
                  </span>
                </div>
              ) : (
                <p className='text-sm text-muted-foreground'>
                  保存后，在“成员分配”中将此策略分配给成员。
                </p>
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
