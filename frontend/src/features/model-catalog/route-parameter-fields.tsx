import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { RequestError } from '@/components/request-state'
import { effortLabels, type ModelValues } from './model-form'

const parameters = [
  'temperature',
  'top_p',
  'reasoning_effort',
  'thinking',
] as const
const efforts = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
  'default',
] as const

export function RouteParameterFields({ index }: { index: number }) {
  const form = useFormContext<ModelValues>()
  const binding = useWatch({ control: form.control, name: `bindings.${index}` })
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState<unknown>(null)
  async function readHint() {
    setLoading(true)
    setError(null)
    try {
      const hint = await api<Schema['ModelHint']>(
        `/llm/channels/${binding.channel_id}/model-hint?${new URLSearchParams({ model_id: binding.upstream_id })}`
      )
      if (hint.source !== 'litellm' || hint.mode !== 'chat') {
        setNotice('未找到精确匹配资料，请手动填写。')
        return
      }
      const current =
        form.getValues(`bindings.${index}.chat_options.limits`) ?? {}
      form.setValue(
        `bindings.${index}.chat_options.limits`,
        {
          ...current,
          context_window: current.context_window ?? hint.context_window,
          max_output: current.max_output ?? hint.max_output,
          parameters:
            current.parameters ??
            (hint.supported_parameters
              ? parameters.filter((p) => hint.supported_parameters!.includes(p))
              : null),
        },
        { shouldDirty: true, shouldValidate: true }
      )
      setNotice('已补全空白项，保存后生效。')
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }
  return (
    <CollapsibleSection
      title='渠道参数限制'
      className='sm:col-span-2'
      open={
        open || !!form.formState.errors.bindings?.[index]?.chat_options?.limits
      }
      onOpenChange={setOpen}
    >
      <div className='flex flex-col gap-4'>
        <div className='flex flex-wrap items-center gap-3'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={loading}
            onClick={() => void readHint()}
          >
            {loading ? '读取中…' : '读取 SDK 资料'}
          </Button>
          <span className='text-sm text-muted-foreground'>
            {notice || '留空沿用模型上限。'}
          </span>
        </div>
        {error != null && <RequestError error={error} />}
        <div className='grid gap-4 sm:grid-cols-2'>
          {(
            [
              ['context_window', '渠道上下文上限'],
              ['max_output', '渠道输出上限'],
            ] as const
          ).map(([key, label]) => (
            <FormField
              key={key}
              control={form.control}
              name={`bindings.${index}.chat_options.limits.${key}`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{label}</FormLabel>
                  <FormControl>
                    <Input
                      value={field.value ?? ''}
                      onChange={(e) =>
                        field.onChange(
                          e.target.value === '' ? null : Number(e.target.value)
                        )
                      }
                      onBlur={field.onBlur}
                      ref={field.ref}
                      name={field.name}
                      type='number'
                      min={1}
                      max={100000000}
                      placeholder='沿用模型上限'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>
        <FormField
          control={form.control}
          name={`bindings.${index}.chat_options.limits.parameters`}
          render={({ field }) => (
            <FormItem>
              <div className='flex items-center justify-between gap-3'>
                <FormLabel>指定可用参数</FormLabel>
                <FormControl>
                  <Switch
                    checked={field.value != null}
                    onCheckedChange={(checked) =>
                      field.onChange(checked ? [...parameters] : null)
                    }
                  />
                </FormControl>
              </div>
              {field.value != null && (
                <div className='flex flex-wrap gap-4'>
                  {parameters.map((p) => (
                    <label key={p} className='flex items-center gap-2 text-sm'>
                      <Checkbox
                        checked={field.value?.includes(p)}
                        onCheckedChange={(checked) =>
                          field.onChange(
                            checked
                              ? [...(field.value ?? []), p]
                              : field.value?.filter((v) => v !== p)
                          )
                        }
                      />
                      {p}
                    </label>
                  ))}
                </div>
              )}
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name={`bindings.${index}.chat_options.limits.reasoning_efforts`}
          render={({ field }) => (
            <FormItem>
              <div className='flex items-center justify-between gap-3'>
                <FormLabel>限定思考强度</FormLabel>
                <FormControl>
                  <Switch
                    checked={field.value != null}
                    onCheckedChange={(checked) =>
                      field.onChange(checked ? [...efforts] : null)
                    }
                  />
                </FormControl>
              </div>
              {field.value != null && (
                <div className='flex flex-wrap gap-4'>
                  {efforts.map((p) => (
                    <label key={p} className='flex items-center gap-2 text-sm'>
                      <Checkbox
                        checked={field.value?.includes(p)}
                        onCheckedChange={(checked) =>
                          field.onChange(
                            checked
                              ? [...(field.value ?? []), p]
                              : field.value?.filter((v) => v !== p)
                          )
                        }
                      />
                      {effortLabels[p]}
                    </label>
                  ))}
                </div>
              )}
              <FormMessage />
            </FormItem>
          )}
        />
      </div>
    </CollapsibleSection>
  )
}
