import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allowAll = true,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  allowAll?: boolean
}) {
  return (
    <Select
      value={value || 'all'}
      onValueChange={(value) => onChange(value === 'all' ? '' : value)}
    >
      <SelectTrigger aria-label={label} className='w-36'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {allowAll && <SelectItem value='all'>全部{label}</SelectItem>}
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
