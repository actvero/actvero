import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { effortLabels, type ModelValues } from './model-form'

export function ChatPolicyFields({ disabled }: { disabled: boolean }) {
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const form = useFormContext<ModelValues>()
  const draft = useWatch({ control: form.control })
  if (draft.kind !== 'chat') return null
  return (
    <div className='mb-6 flex flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>上下文与输出</CardTitle>
        </CardHeader>
        <CardContent className='grid gap-4 sm:grid-cols-2'>
          {(
            [
              ['chat_policy.default_context_window', '默认会话上下文'],
              ['chat_policy.default_max_output', '默认输出上限'],
            ] as const
          ).map(([name, label]) => (
            <FormField
              key={name}
              control={form.control}
              name={name}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{label}</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      inputMode='numeric'
                      placeholder={
                        name.startsWith('chat_policy')
                          ? '沿用模型上限'
                          : '未配置'
                      }
                      disabled={disabled}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
          {(
            [
              ['context_adjustable', '允许调整上下文'],
              ['output_adjustable', '允许调整输出上限'],
            ] as const
          ).map(([name, label]) => (
            <FormField
              key={name}
              control={form.control}
              name={`chat_policy.${name}`}
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-3'>
                  <FormLabel>{label}</FormLabel>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={disabled}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </CardContent>
      </Card>
      {draft.capabilities?.reasoning === 'supported' && (
        <Card>
          <CardHeader>
            <CardTitle>思考设置</CardTitle>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            {draft.reasoning?.effort && (
              <FormField
                control={form.control}
                name='chat_policy.default_reasoning_effort'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>默认思考强度</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={disabled}
                    >
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value='omit'>沿用上游默认</SelectItem>
                          {draft.reasoning?.levels
                            ?.filter((v) => v !== 'omit')
                            .map((v) => (
                              <SelectItem key={v} value={v}>
                                {effortLabels[v]}
                              </SelectItem>
                            ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <FormField
              control={form.control}
              name='chat_policy.reasoning_adjustable'
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-3'>
                  <FormLabel>允许调整思考设置</FormLabel>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={disabled}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>
      )}
      <CollapsibleSection
        title='高级参数'
        open={
          advancedOpen ||
          !!form.formState.errors.chat_policy?.temperature ||
          !!form.formState.errors.chat_policy?.top_p
        }
        onOpenChange={setAdvancedOpen}
      >
        <div className='flex flex-col gap-6'>
          {(['temperature', 'top_p'] as const).map((key) => (
            <div key={key} className='flex flex-col gap-4'>
              <FormField
                control={form.control}
                name={`chat_policy.${key}.enabled`}
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between gap-3'>
                    <FormLabel>配置 {key}</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={disabled}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {draft.chat_policy?.[key]?.enabled && (
                <div className='grid gap-4 sm:grid-cols-3'>
                  {(
                    [
                      ['default', '默认值'],
                      ['min', '下限'],
                      ['max', '上限'],
                    ] as const
                  ).map(([part, label]) => (
                    <FormField
                      key={part}
                      control={form.control}
                      name={`chat_policy.${key}.${part}`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            {key} {label}
                          </FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              inputMode='decimal'
                              placeholder={part === 'default' ? '上游默认' : ''}
                              disabled={disabled}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ))}
                  <FormField
                    control={form.control}
                    name={`chat_policy.${key}.adjustable`}
                    render={({ field }) => (
                      <FormItem className='flex items-center justify-between gap-3 sm:col-span-3'>
                        <FormLabel>允许调整 {key}</FormLabel>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                            disabled={disabled}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </CollapsibleSection>
    </div>
  )
}
