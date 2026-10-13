import { useFieldArray, useFormContext } from 'react-hook-form'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
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
import { newRule, timezones, weekdays, type PolicyValues } from './policy-form'

export function RuleFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<PolicyValues>()
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: 'rules',
  })
  return (
    <section className='flex min-w-0 flex-col gap-4' aria-label='周期额度'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h2 className='font-semibold'>周期额度</h2>
        <div className='flex flex-wrap gap-2'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={disabled || fields.length >= 10}
            onClick={() => append(newRule('fixed_hours'))}
          >
            <Plus />
            小时额度
          </Button>
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={
              disabled ||
              fields.length >= 10 ||
              fields.some((r) => r.kind === 'calendar_week')
            }
            onClick={() => append(newRule('calendar_week'))}
          >
            <Plus />
            周额度
          </Button>
        </div>
      </div>
      {fields.map((r, i) => (
        <Card key={r.id} density='compact'>
          <CardHeader layout='row'>
            <CardTitle size='body'>
              {r.kind === 'fixed_hours' ? '小时额度' : '周额度'}
            </CardTitle>
            <Button
              className='ml-auto'
              type='button'
              variant='ghost'
              size='icon'
              aria-label={`删除第 ${i + 1} 条额度规则`}
              disabled={disabled || fields.length === 1}
              onClick={() => remove(i)}
            >
              <Trash2 />
            </Button>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            <div className='grid gap-4 sm:grid-cols-2'>
              {r.kind === 'fixed_hours' && (
                <FormField
                  control={form.control}
                  name={`rules.${i}.hours`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>时长（小时）</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          inputMode='numeric'
                          placeholder='填写小时数'
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <FormField
                control={form.control}
                name={`rules.${i}.points`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>积分上限</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        inputMode='decimal'
                        placeholder='填写积分'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {r.kind === 'calendar_week' && (
                <>
                  <FormField
                    control={form.control}
                    name={`rules.${i}.week_start`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>周起始日</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                          disabled={disabled}
                        >
                          <FormControl>
                            <SelectTrigger
                              className='w-full'
                              onBlur={field.onBlur}
                              ref={field.ref}
                            >
                              <SelectValue placeholder='选择周起始日' />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectGroup>
                              {weekdays.map((day, n) => (
                                <SelectItem key={day} value={String(n)}>
                                  {day}
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
                    name={`rules.${i}.timezone`}
                    render={({ field }) => (
                      <FormItem className='sm:col-span-2'>
                        <FormLabel>时区</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                          disabled={disabled}
                        >
                          <FormControl>
                            <SelectTrigger
                              className='w-full'
                              onBlur={field.onBlur}
                              ref={field.ref}
                            >
                              <SelectValue placeholder='选择时区' />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectGroup>
                              {[
                                ...new Set([
                                  ...timezones,
                                  ...(field.value ? [field.value] : []),
                                ]),
                              ].map((zone) => (
                                <SelectItem key={zone} value={zone}>
                                  {zone}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </>
              )}
            </div>
            <p className='text-sm text-muted-foreground'>
              {r.kind === 'fixed_hours'
                ? '首次使用起算，到期后下一次使用重新计时。'
                : '按所选时区，在周起始日 00:00 重置。'}
            </p>
          </CardContent>
        </Card>
      ))}
    </section>
  )
}
