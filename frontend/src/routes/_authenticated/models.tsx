import { createFileRoute } from '@tanstack/react-router'
import { modelsSearchSchema } from '@/vendor/newapi/features/models/search-schema'
import { AccessGate } from '@/features/auth/gate'
import { GatewayPage } from '@/features/model-gateway/page'

export const Route = createFileRoute('/_authenticated/models')({
  validateSearch: modelsSearchSchema,
  component: () => (
    <AccessGate admin>
      <GatewayPage view='models' />
    </AccessGate>
  ),
})
