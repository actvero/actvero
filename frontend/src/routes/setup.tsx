import { createFileRoute } from '@tanstack/react-router'
import { SetupPage } from '@/features/auth/setup'

export const Route = createFileRoute('/setup')({ component: SetupPage })
