import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ModelChannelsPage } from '@/features/model-channels/page'

export const Route = createFileRoute('/_authenticated/model-channels')({
  component: () => (
    <AccessGate admin>
      <ModelChannelsPage />
    </AccessGate>
  ),
})
