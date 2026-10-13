import { createFileRoute } from '@tanstack/react-router'
import { HomeRedirect } from '@/features/auth/gate'

export const Route = createFileRoute('/console')({ component: HomeRedirect })
