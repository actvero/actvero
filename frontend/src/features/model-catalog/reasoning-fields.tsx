import { useFormContext, useWatch } from 'react-hook-form'
import { Checkbox } from '@/components/ui/checkbox'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { effortLabels, effortLevels, type ModelValues } from './model-form'

export function ReasoningFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<ModelValues>()
  const support = useWatch({
    control: form.control,
    name: 'capabilities.reasoning',
  })
  const reasoning = useWatch({ control: form.control, name: 'reasoning' })
  if (support !== 'supported') return null
  return (
    <div className='flex flex-col gap-4'>
      <Separator />
      <div className='flex flex-wrap gap-5'>
        {(
          [
            ['toggle', '可开关'],
            ['effort', '可调强度'],
            ['budget', '可调预算'],
          ] as const
        ).map(([key, label]) => (
          <FormField
            key={key}
            control={form.control}
            name={`reasoning.${key}`}
            render={({ field }) => (
              <FormItem className='flex items-center gap-2'>
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(v) => field.onChange(v === true)}
                    disabled={disabled}
                  />
                </FormControl>
                <FormLabel>{label}</FormLabel>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
      </div>
      {reasoning.effort && (
        <FormField
          control={form.control}
          name='reasoning.levels'
          render={({ field }) => (
            <FormItem>
              <FormControl>
                <fieldset
                  disabled={disabled}
                  className='flex flex-wrap gap-x-5 gap-y-3'
                >
                  <legend className='mb-3 text-sm font-medium'>
                    支持的强度
                  </legend>
                  {effortLevels.map((level) => (
                    <label
                      key={level}
                      className='flex items-center gap-2 text-sm'
                    >
                      <Checkbox
                        checked={field.value.includes(level)}
                        onCheckedChange={(checked) =>
                          field.onChange(
                            checked
                              ? [...field.value, level]
                              : field.value.filter((v) => v !== level)
                          )
                        }
                      />
                      {effortLabels[level]}
                    </label>
                  ))}
                </fieldset>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
      {reasoning.budget && (
        <div className='grid gap-4 sm:grid-cols-2'>
          {(
            [
              ['min', '预算下限'],
              ['max', '预算上限'],
            ] as const
          ).map(([key, label]) => (
            <FormField
              key={key}
              control={form.control}
              name={`reasoning.${key}`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{label}（Token）</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      inputMode='numeric'
                      placeholder='未配置'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>
      )}
    </div>
  )
}
