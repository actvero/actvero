import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { LoginPage } from '@/features/auth/login'
import { loginReturnTo } from '@/features/auth/return-to'

export const Route = createFileRoute('/login')({
  validateSearch: z.object({
    error: z.string().optional(),
    next: z.unknown().optional().transform(loginReturnTo),
  }),
  component: LoginPage,
})
