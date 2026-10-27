import { type ComponentProps, type ReactNode } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function TextField({
  label,
  error,
  ...props
}: ComponentProps<typeof Input> & { label: string; error?: string }) {
  return (
    <Field data-invalid={!!error}>
      <FieldLabel htmlFor={props.id}>{label}</FieldLabel>
      <Input {...props} aria-invalid={!!error} />
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

export function Choice({
  label,
  id,
  value,
  onChange,
  choices,
}: {
  label: string
  id: string
  value: string
  onChange: (value: string) => void
  choices: [string, string][]
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {choices.map(([v, n]) => (
              <SelectItem key={v} value={v}>
                {n}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

export function Editor({
  title,
  description,
  busy,
  close,
  children,
}: {
  title: string
  description?: string
  busy: boolean
  close: () => void
  children: ReactNode
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <DialogContent
        aria-describedby={undefined}
        className='max-h-[90dvh] overflow-y-auto sm:max-w-2xl'
        onInteractOutside={(e) => {
          if (busy) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}
