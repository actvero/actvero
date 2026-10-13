import { ResourceCategoriesDialog } from '@/components/resource-categories-dialog'

export function CategoriesDialog({ close }: { close: () => void }) {
  return (
    <ResourceCategoriesDialog resource='skills' noun='技能' close={close} />
  )
}
