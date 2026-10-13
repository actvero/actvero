import * as React from 'react'
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group'
import { CircleIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

function RadioGroup({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<typeof RadioGroupPrimitive.Root> & {
  variant?: 'default' | 'segmented'
}) {
  return (
    <RadioGroupPrimitive.Root
      data-slot='radio-group'
      className={cn(
        variant === 'segmented'
          ? 'flex w-fit flex-wrap gap-1 rounded-lg bg-muted p-1'
          : 'grid gap-3',
        className
      )}
      {...props}
    />
  )
}

function RadioGroupItem({
  className,
  variant = 'default',
  children,
  ...props
}: React.ComponentProps<typeof RadioGroupPrimitive.Item> & {
  variant?: 'default' | 'segmented'
}) {
  return (
    <RadioGroupPrimitive.Item
      data-slot='radio-group-item'
      className={cn(
        variant === 'segmented'
          ? 'inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-[color,box-shadow] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 data-[state=checked]:bg-background data-[state=checked]:text-foreground data-[state=checked]:shadow-sm'
          : 'aspect-square size-4 shrink-0 rounded-full border border-input text-primary shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:bg-input/30 dark:aria-invalid:ring-destructive/40',
        className
      )}
      {...props}
    >
      {variant === 'segmented' ? (
        children
      ) : (
        <RadioGroupPrimitive.Indicator
          data-slot='radio-group-indicator'
          className='relative flex items-center justify-center'
        >
          <CircleIcon className='absolute top-1/2 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 fill-primary' />
        </RadioGroupPrimitive.Indicator>
      )}
    </RadioGroupPrimitive.Item>
  )
}

export { RadioGroup, RadioGroupItem }
