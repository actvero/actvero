import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/_authenticated/system/')({
  component: () => <Navigate to='/system/general' replace />,
})
