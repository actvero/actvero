import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { McpRoutePage } from '@/features/mcp/route-page'

export const Route = createFileRoute('/_authenticated/mcp')({
  component: () => (
    <AccessGate>
      <McpRoutePage />
    </AccessGate>
  ),
})
