import type { ComponentProps } from 'react'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'

export function Choice({
  value,
  onChange,
  options,
  label,
  disabled,
  ...triggerProps
}: {
  value: string
  onChange: (v: string) => void
  options: Record<string, string>
  label: string
  disabled?: boolean
} & Omit<ComponentProps<typeof SelectTrigger>, 'value' | 'onChange'>) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger aria-label={label} className='w-full' {...triggerProps}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {Object.entries(options).map(([k, v]) => (
            <SelectItem key={k} value={k}>
              {v}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
