import { useId, type ComponentProps, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

export function EditorDialog({
  title,
  description,
  children,
  onClose,
  wide = false,
}: {
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const descriptionId = useId()
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        aria-describedby={description ? descriptionId : undefined}
        className={
          wide
            ? 'max-h-[90dvh] overflow-y-auto sm:max-w-5xl'
            : 'max-h-[90dvh] overflow-y-auto sm:max-w-2xl'
        }
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && (
            <DialogDescription id={descriptionId}>
              {description}
            </DialogDescription>
          )}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}
export function TextField({
  label,
  hint,
  ...props
}: ComponentProps<typeof Input> & { label: string; hint?: string }) {
  const id = useId()
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input id={id} {...props} />
      {hint && <FieldDescription>{hint}</FieldDescription>}
    </Field>
  )
}
export function AreaField({
  label,
  hint,
  ...props
}: ComponentProps<typeof Textarea> & { label: string; hint?: string }) {
  const id = useId()
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Textarea id={id} {...props} />
      {hint && <FieldDescription>{hint}</FieldDescription>}
    </Field>
  )
}
export function ChoiceField({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  hint?: string
}) {
  const id = useId()
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className='w-full'>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {options.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {hint && <FieldDescription>{hint}</FieldDescription>}
    </Field>
  )
}
export function SaveActions({
  pending,
  onClose,
  label = '保存',
}: {
  pending: boolean
  onClose: () => void
  label?: string
}) {
  return (
    <div className='flex justify-end gap-2 border-t pt-4'>
      <Button
        type='button'
        variant='outline'
        onClick={onClose}
        disabled={pending}
      >
        取消
      </Button>
      <Button type='submit' disabled={pending}>
        {pending ? '正在保存…' : label}
      </Button>
    </div>
  )
}
