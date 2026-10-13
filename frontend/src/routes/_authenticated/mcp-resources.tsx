import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/_authenticated/mcp-resources')({
  beforeLoad: () => {
    throw redirect({ to: '/mcp' })
  },
})
