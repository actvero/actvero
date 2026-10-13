import { useFormContext } from 'react-hook-form'
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
import {
  imageSizes,
  imageQualities,
} from '@/features/model-channels/image-test-schema'
import type { ModelValues } from './model-form'

export function ImageFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<ModelValues>()
  return (
    <Card>
      <CardHeader>
        <CardTitle>图片生成</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        <div className='grid gap-4 sm:grid-cols-2'>
          {(
            [
              ['size', '尺寸', imageSizes],
              ['quality', '质量', imageQualities],
            ] as const
          ).map(([name, label, choices]) => (
            <FormField
              key={name}
              control={form.control}
              name={`image.${name}`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{label}</FormLabel>
                  <Select
                    value={field.value || 'default'}
                    onValueChange={(v) =>
                      field.onChange(v === 'default' ? '' : v)
                    }
                    disabled={disabled}
                  >
                    <FormControl>
                      <SelectTrigger className='w-full'>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value='default'>上游默认</SelectItem>
                        {choices.map((v) => (
                          <SelectItem key={v} value={v}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>
        <FormField
          control={form.control}
          name='image.max_prompt_characters'
          render={({ field }) => (
            <FormItem>
              <FormLabel>提示词上限（字符）</FormLabel>
              <FormControl>
                <Input {...field} inputMode='numeric' disabled={disabled} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <p className='text-sm text-muted-foreground'>
          每次生成 1 张，使用此处的尺寸和质量。
        </p>
      </CardContent>
    </Card>
  )
}
