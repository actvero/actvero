import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/_authenticated/mcp-prompts')({
  beforeLoad: () => {
    throw redirect({ to: '/mcp' })
  },
})
