import { createFileRoute, Outlet } from '@tanstack/react-router'

export const Route = createFileRoute('/platform/settings')({
  component: Outlet,
})
