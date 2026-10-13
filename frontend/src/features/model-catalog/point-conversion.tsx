import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { currencies } from './model-form'

const schema = z.object({
  currency: z
    .string()
    .refine(
      (v) => (currencies as readonly string[]).includes(v),
      '选择计价币种'
    ),
  points_per_currency: z
    .string()
    .regex(/^(0|[1-9][0-9]{0,12})(\.[0-9]{1,12})?$/, '填写正数，最多 12 位小数')
    .refine(
      (v) => Number(v) > 0 && Number(v) <= 1e12,
      '比例须大于 0 且不超过 1000000000000'
    ),
})

export function PointConversionButton() {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!pending) setOpen(v)
      }}
    >
      <DialogTrigger asChild>
        <Button type='button' variant='outline'>
          <ArrowRightLeft />
          积分换算
        </Button>
      </DialogTrigger>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>模型积分换算</DialogTitle>
        </DialogHeader>
        {open && (
          <ConversionLoader
            close={() => setOpen(false)}
            pendingChanged={setPending}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function ConversionLoader({
  close,
  pendingChanged,
}: {
  close: () => void
  pendingChanged: (value: boolean) => void
}) {
  const { organization } = useOrganization()
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, 'llm-point-conversion'],
    queryFn: ({ signal }) =>
      api<Schema['PointConversionSettings']>(
        '/llm/point-conversion',
        'GET',
        undefined,
        undefined,
        signal
      ),
    refetchOnWindowFocus: false,
  })
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <ConversionForm
      conversion={query.data.conversion}
      close={close}
      pendingChanged={pendingChanged}
    />
  )
}

function ConversionForm({
  conversion,
  close,
  pendingChanged,
}: {
  conversion: Schema['PointConversionView'] | null
  close: () => void
  pendingChanged: (value: boolean) => void
}) {
  const { csrf, organization } = useOrganization()
  const client = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  // Keep the version from when this form opened; a background refresh must not authorize an overwrite.
  const [version] = useState(conversion?.version ?? 0)
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      currency: conversion?.currency ?? '',
      points_per_currency: conversion?.points_per_currency ?? '',
    },
  })
  const busy = form.formState.isSubmitting
  async function submit(values: z.infer<typeof schema>) {
    setError(null)
    pendingChanged(true)
    try {
      const result = await api<Schema['PointConversionSettings']>(
        '/llm/point-conversion',
        'PUT',
        { ...values, version },
        csrf
      )
      client.setQueryData(
        ['organization', organization.tenant_id, 'llm-point-conversion'],
        result
      )
      for (const feature of ['model-catalog', 'llm-point-prices'])
        void client.invalidateQueries({
          queryKey: ['organization', organization.tenant_id, feature],
        })
      toast.success('积分换算已保存')
      close()
    } catch (e) {
      setError(e)
    } finally {
      pendingChanged(false)
    }
  }
  return (
    <Form {...form}>
      <form
        className='flex flex-col gap-5'
        onSubmit={(e) => {
          e.stopPropagation()
          void form.handleSubmit(submit)(e)
        }}
      >
        <FormField
          control={form.control}
          name='currency'
          render={({ field }) => (
            <FormItem>
              <FormLabel>计价币种</FormLabel>
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={busy}
              >
                <FormControl>
                  <SelectTrigger
                    className='w-full'
                    ref={field.ref}
                    onBlur={field.onBlur}
                  >
                    <SelectValue placeholder='选择币种' />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    {currencies.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
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
          name='points_per_currency'
          render={({ field }) => (
            <FormItem>
              <FormLabel>每 1 单位货币对应积分</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  inputMode='decimal'
                  disabled={busy}
                  placeholder='填写换算比例'
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <p className='text-sm text-muted-foreground'>
          适用于全部模型的成员预算价格。币种不一致的模型需先调整价格，不自动换汇。
        </p>
        {!!error && <RequestError error={error} />}
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={busy}
            onClick={close}
          >
            取消
          </Button>
          <Button disabled={busy}>{busy ? '保存中…' : '保存换算'}</Button>
        </DialogFooter>
      </form>
    </Form>
  )
}
