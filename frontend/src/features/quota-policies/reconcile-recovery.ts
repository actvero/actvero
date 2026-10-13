import { z } from 'zod'

export const recoverySchema = z
  .object({ call_id: z.string().uuid(), request_id: z.string().uuid() })
  .strict()
export type ReconcileRecovery = z.infer<typeof recoverySchema>

export function recoveryKey(tenantId: string, userId: string, callId: string) {
  return `settlement-reconcile:${tenantId}:${userId}:${callId}`
}

export function readRecovery(
  key: string,
  callId: string
): ReconcileRecovery | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const parsed = recoverySchema.safeParse(JSON.parse(raw))
    return parsed.success && parsed.data.call_id === callId ? parsed.data : null
  } catch {
    return null
  }
}

export function pendingRecoveries(
  tenantId: string,
  userId: string
): ReconcileRecovery[] {
  const prefix = recoveryKey(tenantId, userId, '')
  const items: ReconcileRecovery[] = []
  try {
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index)
      if (!key?.startsWith(prefix)) continue
      const callId = key.slice(prefix.length)
      const recovered = readRecovery(key, callId)
      if (recovered) items.push(recovered)
    }
  } catch {
    return []
  }
  return items
}
