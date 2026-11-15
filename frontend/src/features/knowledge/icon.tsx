import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import {
  selectedIcon,
  useResourceIconCatalog,
  type IconSelection,
} from '@/lib/resource-icons'
import { Avatar, AvatarImage } from '@/components/ui/avatar'
import { IconPicker } from '@/components/icon-picker'
import { ResourceIconButton } from '@/components/resource-icon'
import { useKnowledge, type Base } from './shared'

export function KnowledgeAvatar({
  image,
  size = 'md',
}: {
  image: string
  size?: 'sm' | 'md'
}) {
  return (
    <Avatar size={size}>
      <AvatarImage src={image} alt='' />
    </Avatar>
  )
}

export function KnowledgeIconField({
  name,
  value = { source: 'auto' },
  onChange,
  immediate = false,
  size = 'lg',
  showCamera,
}: {
  name: string
  value?: IconSelection
  onChange: (value: IconSelection) => void | Promise<void>
  immediate?: boolean
  size?: 'sm' | 'md' | 'lg'
  showCamera?: boolean
}) {
  const [open, setOpen] = useState(false)
  const query = useResourceIconCatalog(
    open || (value.source === 'library' && !value.image)
  )
  const options = query.data ?? []
  const choice: IconSelection =
    value.source === 'library' ? { source: 'library', key: value.key } : value
  const image = selectedIcon(choice, options) || value.image
  const action = image ? '编辑知识库头像' : '添加知识库头像'
  return (
    <>
      <ResourceIconButton
        image={image}
        name={name}
        size={size}
        showCamera={showCamera}
        fallback={
          <BookOpen className='size-5 text-muted-foreground' aria-hidden />
        }
        label={action}
        onClick={() => setOpen(true)}
      />
      {open && (
        <IconPicker
          title='选择知识库头像'
          description={
            immediate ? '确认后更新知识库头像。' : '随知识库信息一起保存。'
          }
          showAutomatic={false}
          value={choice}
          name={name}
          options={options}
          loading={query.isPending}
          error={query.error}
          retry={() => void query.refetch()}
          onChange={onChange}
          close={() => setOpen(false)}
        />
      )}
    </>
  )
}

export function SavedKnowledgeIcon({
  base,
  editable = base.can_manage,
  size = 'md',
  showCamera,
  onSaved,
}: {
  base: Base
  editable?: boolean
  size?: 'sm' | 'md'
  showCamera?: boolean
  onSaved?: (base: Base) => void
}) {
  const { csrf, key, refresh } = useKnowledge()
  const client = useQueryClient()
  const path = `/knowledge/${base.id}`
  const save = useMutation({
    mutationFn: (icon: IconSelection) => {
      const update: Schema['KnowledgeIconUpdate'] = {
        version: base.version,
        icon_selection: { key: '', image: '', ...icon },
      }
      return api<Base>(path + '/icon', 'PATCH', update, csrf)
    },
    onSuccess: (updated) => {
      client.setQueryData([...key, path], updated)
      onSaved?.(updated)
      void refresh()
      toast.success('知识库头像已更新')
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        await refresh()
        if (onSaved) {
          const current = await api<Base>(path).catch(() => undefined)
          if (current) onSaved(current)
        }
      }
    },
  })

  if (!editable) {
    return base.icon?.image ? (
      <KnowledgeAvatar image={base.icon.image} size={size} />
    ) : null
  }
  return (
    <KnowledgeIconField
      name={base.name}
      value={base.icon}
      immediate
      size={size}
      showCamera={showCamera}
      onChange={async (icon) => {
        await save.mutateAsync(icon)
      }}
    />
  )
}
