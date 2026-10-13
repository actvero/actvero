import { useId } from 'react'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from '@/components/ui/input-group'
import { Label } from '@/components/ui/label'

export function CopyableField({
  value,
  label,
  hideLabel = false,
  copyLabel = '复制',
}: {
  value: string
  label: string
  hideLabel?: boolean
  copyLabel?: string
}) {
  const id = useId()
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      toast.success('已复制')
    } catch {
      toast.error('复制失败，请手动选择复制')
    }
  }
  return (
    <div className='grid min-w-0 gap-2'>
      {!hideLabel && <Label htmlFor={id}>{label}</Label>}
      <InputGroup>
        <InputGroupInput
          id={id}
          aria-label={hideLabel ? label : undefined}
          value={value}
          readOnly
          autoComplete='off'
        />
        <InputGroupAddon align='inline-end'>
          <InputGroupButton
            size='icon-sm'
            aria-label={copyLabel}
            title={copyLabel}
            onClick={() => void copy()}
          >
            <Copy />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </div>
  )
}
