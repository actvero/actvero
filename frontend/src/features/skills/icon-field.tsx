import { useState } from 'react'
import {
  selectedIcon,
  useResourceIconCatalog,
  type IconSelection,
} from '@/lib/resource-icons'
import { IconPicker } from '@/components/icon-picker'
import { ResourceIconButton } from '@/components/resource-icon'

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
  const [open, setOpen] = useState(false)
  const query = useResourceIconCatalog(open || value.source === 'library')
  const options = query.data ?? []
  return (
    <>
      <ResourceIconButton
        image={selectedIcon(value, options, packageIcon)}
        name={name}
        label='编辑技能图标'
        disabled={disabled}
        onClick={() => setOpen(true)}
      />
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
