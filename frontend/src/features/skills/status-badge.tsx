import { Badge } from '@/components/ui/badge'
import { statusLabels, type Version } from './shared'

export function SkillStatusBadge({
  status,
}: {
  status: Version['status'] | 'inactive'
}) {
  return (
    <Badge dot variant={status === 'published' ? 'success' : 'secondary'}>
      {status === 'inactive' ? '未生效' : statusLabels[status]}
    </Badge>
  )
}
