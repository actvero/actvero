import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
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
import { Textarea } from '@/components/ui/textarea'
import type { BatchValues } from './diagnostic-batch-values'
import { diagnosticFormSchema } from './diagnostic-form'

export function BatchParameters({
  values,
  label,
  onSave,
  onCancel,
}: {
  values: BatchValues
  label: string
  onSave: (values: BatchValues) => void
  onCancel: () => void
}) {
  const form = useForm<BatchValues>({
    resolver: zodResolver(diagnosticFormSchema),
    defaultValues: values,
  })
  const operation = values.operation
  return (
    <Form {...form}>
      <form
        className='flex min-w-0 flex-col gap-3 rounded-md border p-3'
        onSubmit={(event) =>
          void form.handleSubmit((next) => onSave(next))(event)
        }
      >
        <strong className='text-sm break-words'>{label}</strong>
        {operation === 'rerank' && (
          <FormField
            control={form.control}
            name='query'
            render={({ field }) => (
              <FormItem>
                <FormLabel>查询内容</FormLabel>
                <FormControl>
                  <Input {...field} maxLength={2000} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
        <FormField
          control={form.control}
          name='texts'
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                {operation === 'chat'
                  ? '测试提示词'
                  : operation === 'embedding'
                    ? '输入文本（每行一条）'
                    : '候选文档（每行一篇）'}
              </FormLabel>
              <FormControl>
                <Textarea
                  {...field}
                  rows={3}
                  maxLength={operation === 'chat' ? 2000 : 16007}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='count'
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                {operation === 'chat'
                  ? '最大输出 Token'
                  : operation === 'embedding'
                    ? '维度（选填）'
                    : '返回数量（选填）'}
              </FormLabel>
              <FormControl>
                <Input {...field} inputMode='numeric' />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='flex flex-wrap gap-2'>
          <Button type='submit' size='sm'>
            保存参数
          </Button>
          <Button type='button' variant='outline' size='sm' onClick={onCancel}>
            取消编辑
          </Button>
        </div>
      </form>
    </Form>
  )
}
