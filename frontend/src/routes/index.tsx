import { createFileRoute } from '@tanstack/react-router'
import { HomePage } from '@/features/portal/home-page'

export const Route = createFileRoute('/')({ component: HomePage })
