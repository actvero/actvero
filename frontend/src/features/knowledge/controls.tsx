import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { states } from './shared'

export function State({ value }: { value: string }) {
  const attention = value === 'attention' || value === 'unconfigured'
  return (
    <Badge
      dot
      variant={
        ['failed', 'uncertain'].includes(value)
          ? 'destructive'
          : attention
            ? 'outline'
            : value === 'ready'
              ? 'success'
              : 'secondary'
      }
      className={attention ? 'border-warning/30 bg-warning/10' : undefined}
    >
      {states[value] ?? value}
    </Badge>
  )
}
export function Choice({
  value,
  onChange,
  items,
  label,
  disabled = false,
}: {
  value: string
  onChange: (value: string) => void
  items: { value: string; label: string }[]
  label: string
  disabled?: boolean
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger aria-label={label}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
