import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AccountPage } from '@/features/account/page'

export const Route = createFileRoute('/_authenticated/account')({
  validateSearch: z.object({
    tab: z
      .enum(['profile', 'security', 'devices'])
      .optional()
      .catch(undefined),
    password: z.enum(['cancelled', 'error']).optional().catch(undefined),
  }),
  component: AccountPage,
})
