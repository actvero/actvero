import { useState } from 'react'
import { z } from 'zod'
import { useForm, useFieldArray, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Plug, Plus, Trash2, Eye } from 'lucide-react'
import { toast } from 'sonner'
import { avatarDataUrl } from '@/lib/avatar-image'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
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
import { Textarea } from '@/components/ui/textarea'
import { AvatarEditor } from '@/components/avatar-editor'
import { RequestError } from '@/components/request-state'
import { useMcp, useReturnFocus, type Service } from './shared'

export function ServiceIcon({
  name,
  icon,
  size = 'sm',
}: {
  name: string
  icon?: string
  size?: 'sm' | 'md'
}) {
  return (
    <Avatar size={size}>
      <AvatarImage src={icon || undefined} alt={name} />
      <AvatarFallback>
        <Plug className='size-4' />
      </AvatarFallback>
    </Avatar>
  )
}
const schema = z.object({
  display_name: z.string().trim().min(1, '请输入显示名称').max(100),
  description: z.string().trim().max(2000),
  icon: z.string(),
  examples: z
    .array(
      z.object({ value: z.string().trim().min(1, '请输入使用示例').max(500) })
    )
    .max(8),
})
export function Presentation({ service }: { service: Service }) {
  const { write, invalidate } = useMcp()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [preview, setPreview] = useState(false)
  const [readingIcon, setReadingIcon] = useState(false)
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: service.display_name || service.name,
      description: service.description || '',
      icon: service.icon || '',
      examples: (service.examples || []).map((value) => ({ value })),
    },
  })
  const fields = useFieldArray({ control: form.control, name: 'examples' })
  const values = useWatch({ control: form.control })
  return (
    <Form {...form}>
      <form
        className='flex max-w-3xl flex-col gap-5'
        onSubmit={form.handleSubmit(async (v) => {
          setPending(true)
          setError(null)
          try {
            await write(`/services/${service.id}/presentation`, 'PUT', {
              ...v,
              examples: v.examples.map((e) => e.value),
              version: service.version,
            })
            form.reset(v)
            await invalidate()
            toast.success('已保存展示设置')
          } catch (e) {
            setError(e)
          } finally {
            setPending(false)
          }
        })}
      >
        <div className='flex items-center gap-5'>
          <FormField
            control={form.control}
            name='icon'
            render={({ field }) => (
              <FormItem>
                <FormLabel className='sr-only'>连接器图标</FormLabel>
                <AvatarEditor
                  value={field.value}
                  fallback={<Plug className='size-6' />}
                  label='连接器图标'
                  disabled={pending || readingIcon}
                  onChange={async (file) => {
                    setReadingIcon(true)
                    try {
                      field.onChange(file ? await avatarDataUrl(file) : '')
                      form.clearErrors('icon')
                    } finally {
                      setReadingIcon(false)
                    }
                  }}
                />
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='display_name'
            render={({ field }) => (
              <FormItem className='min-w-0 flex-1'>
                <FormLabel>显示名称</FormLabel>
                <FormControl>
                  <Input {...field} disabled={pending || readingIcon} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <FormField
          control={form.control}
          name='description'
          render={({ field }) => (
            <FormItem>
              <FormLabel>简介</FormLabel>
              <FormControl>
                <Textarea
                  {...field}
                  rows={3}
                  disabled={pending || readingIcon}
                  placeholder='这个连接器能帮助用户做什么'
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <fieldset className='flex flex-col gap-3'>
          <legend className='mb-3 text-sm font-medium'>使用示例</legend>
          {fields.fields.map((f, i) => (
            <div key={f.id} className='flex items-start gap-2'>
              <FormField
                control={form.control}
                name={`examples.${i}.value`}
                render={({ field }) => (
                  <FormItem className='flex-1'>
                    <FormLabel className='sr-only'>使用示例 {i + 1}</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        disabled={pending || readingIcon}
                        placeholder='例如：帮我汇总本周收到的客户反馈'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button
                type='button'
                variant='ghost'
                size='icon'
                aria-label={`删除示例 ${i + 1}`}
                disabled={pending || readingIcon}
                onClick={() => fields.remove(i)}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
          <Button
            className='self-start'
            type='button'
            variant='outline'
            size='sm'
            disabled={pending || fields.fields.length >= 8}
            onClick={() => fields.append({ value: '' })}
          >
            <Plus />
            添加示例
          </Button>
        </fieldset>
        {!!error && <RequestError error={error} />}
        <div className='flex justify-end gap-2'>
          <Button
            type='button'
            variant='outline'
            onClick={() => setPreview(true)}
          >
            <Eye />
            预览连接器
          </Button>
          <Button disabled={pending || readingIcon}>保存展示设置</Button>
        </div>
        {preview && (
          <ConnectorPreview
            close={() => setPreview(false)}
            name={values.display_name || service.name}
            description={values.description || ''}
            icon={values.icon}
            examples={(values.examples || [])
              .map((e) => e?.value || '')
              .filter(Boolean)}
          />
        )}
      </form>
    </Form>
  )
}
function ConnectorPreview({
  name,
  description,
  icon,
  examples,
  close,
}: {
  name: string
  description: string
  icon?: string
  examples: string[]
  close: () => void
}) {
  const restore = useReturnFocus()
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v) close()
      }}
    >
      <DialogContent
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg'
        onCloseAutoFocus={restore}
      >
        <DialogHeader>
          <DialogTitle>连接器预览</DialogTitle>
          <DialogDescription>列表和详情共用同一份简介。</DialogDescription>
        </DialogHeader>
        <Card>
          <CardHeader>
            <div className='flex items-center gap-3'>
              <ServiceIcon name={name} icon={icon} />
              <CardTitle className='min-w-0 break-words'>{name}</CardTitle>
            </div>
            <CardDescription className='break-words whitespace-pre-wrap'>
              {description || '暂无简介'}
            </CardDescription>
          </CardHeader>
          {examples.length > 0 && (
            <CardContent className='flex flex-col gap-3'>
              <p className='text-sm font-medium'>使用示例</p>
              {examples.map((e, i) => (
                <p className='text-sm break-words' key={i}>
                  {e}
                </p>
              ))}
            </CardContent>
          )}
        </Card>
      </DialogContent>
    </Dialog>
  )
}
