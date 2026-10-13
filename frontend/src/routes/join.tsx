import { createFileRoute } from '@tanstack/react-router'
import { JoinPage } from '@/features/auth/join'

export const Route = createFileRoute('/join')({ component: JoinPage })
