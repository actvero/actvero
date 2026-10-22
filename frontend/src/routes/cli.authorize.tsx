import { createFileRoute } from '@tanstack/react-router'
import { CliAuthorizePage } from '@/features/auth/cli-authorize'

export const Route = createFileRoute('/cli/authorize')({
  component: CliAuthorizePage,
})
