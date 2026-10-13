import { useFormContext } from 'react-hook-form'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
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
  type ImageTestFields,
} from './image-test-schema'

const options = [
  { name: 'size', label: '图片尺寸', values: imageSizes },
  { name: 'quality', label: '画质', values: imageQualities },
] as const

export function ImageTestOptions({ disabled }: { disabled: boolean }) {
  const { control } = useFormContext<ImageTestFields>()
  return (
    <div className='grid gap-4 sm:grid-cols-2'>
      {options.map(({ name, label, values }) => (
        <FormField
          key={name}
          control={control}
          name={name}
          render={({ field }) => (
            <FormItem>
              <FormLabel>{label}</FormLabel>
              <Select
                value={field.value || 'default'}
                onValueChange={(value) =>
                  field.onChange(value === 'default' ? '' : value)
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
                    {values.map((value) => (
                      <SelectItem key={value} value={value}>
                        {value}
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
  )
}
