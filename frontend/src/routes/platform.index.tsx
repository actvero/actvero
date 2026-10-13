import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/platform/')({
  component: () => <Navigate to='/platform/organizations' replace />,
})
