import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { GatewayStatistics } from '@/features/model-gateway/statistics'

export const Route = createFileRoute('/_authenticated/llm-usage')({
  component: function Page() {
    return (
      <AccessGate admin>
        <GatewayStatistics />
      </AccessGate>
    )
  },
})
