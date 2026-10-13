import { useId, useState, type ComponentProps } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

type Props = Omit<ComponentProps<typeof Button>, 'value' | 'onChange'> & {
  items: { value: string; label: string }[]
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  searchPlaceholder?: string
}

/** Searchable single selection, sharing Radix focus and cmdk keyboard behavior. */
export function SearchSelect({
  items,
  value,
  onValueChange,
  placeholder = '请选择',
  searchPlaceholder = '搜索…',
  className,
  ...props
}: Props) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          {...props}
          type='button'
          variant='outline'
          role='combobox'
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          className={cn('min-w-0 justify-between', className)}
        >
          <span className='truncate'>
            {items.find((item) => item.value === value)?.label ?? placeholder}
          </span>
          <ChevronsUpDown aria-hidden='true' />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='start'
        className='w-(--radix-popover-trigger-width) max-w-[calc(100vw-2rem)] min-w-48 p-0'
      >
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
          />
          <CommandList id={id} className='max-h-56'>
            <CommandEmpty>没有匹配的选项</CommandEmpty>
            <CommandGroup>
              {items.map((item) => (
                <CommandItem
                  key={item.value}
                  value={item.value}
                  keywords={[item.label]}
                  onSelect={() => {
                    onValueChange(item.value)
                    setOpen(false)
                  }}
                >
                  <span className='min-w-0 flex-1 truncate'>{item.label}</span>
                  {value === item.value && <Check aria-label='已选择' />}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
