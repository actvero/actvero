import { z } from 'zod'

export const memberSearch = z.object({
  page: z.number().int().positive().catch(1),
  q: z.string().catch(''),
  role: z.enum(['', 'administrator', 'member']).catch(''),
  status: z.string().catch(''),
  tab: z.enum(['members', 'invitations']).catch('members'),
})
