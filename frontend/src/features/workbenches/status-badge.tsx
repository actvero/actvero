import { Badge } from '@/components/ui/badge'
import { statuses, type WorkbenchVersion } from './shared'

export function WorkbenchStatusBadge({
  status,
}: {
  status: WorkbenchVersion['status']
}) {
  return (
    <Badge variant={status === 'published' ? 'secondary' : 'outline'}>
      {statuses[status]}
    </Badge>
  )
}
