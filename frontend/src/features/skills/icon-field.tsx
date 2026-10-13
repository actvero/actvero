import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Camera } from 'lucide-react'
import { api } from '@/lib/api'
import {
  selectedIcon,
  type IconSelection,
  type IconOption,
} from '@/lib/resource-icons'
import { Button } from '@/components/ui/button'
import { IconPicker } from '@/components/icon-picker'
import { ResourceIcon } from '@/components/resource-icon'
import { useSkills } from './shared'

export function SkillIconField({
  value = { source: 'auto' },
  onChange,
  name,
  disabled,
  packageIcon,
  warning,
}: {
  value?: IconSelection
  onChange: (value: IconSelection) => void
  name: string
  disabled: boolean
  packageIcon?: string
  warning?: string
}) {
  const { key } = useSkills()
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: [...key, 'icon-catalog'],
    queryFn: () => api<IconOption[]>('/skills/icon-catalog'),
    staleTime: Infinity,
  })
  const options = query.data ?? []
  return (
    <>
      <Button
        type='button'
        variant='ghost'
        className='relative h-auto shrink-0 p-1'
        aria-label='编辑技能图标'
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <ResourceIcon
          image={selectedIcon(value, options, packageIcon)}
          name={name}
          size='lg'
        />
        <Camera className='absolute right-0 bottom-0 size-4' />
      </Button>
      {open && (
        <IconPicker
          value={value}
          name={name}
          options={options}
          loading={query.isPending}
          error={query.error}
          retry={() => void query.refetch()}
          automaticImage={packageIcon}
          automaticWarning={warning}
          onChange={onChange}
          close={() => setOpen(false)}
        />
      )}
    </>
  )
}
