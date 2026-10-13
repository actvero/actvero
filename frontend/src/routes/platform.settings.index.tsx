import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/platform/settings/')({
  component: () => <Navigate to='/platform/settings/general' replace />,
})
