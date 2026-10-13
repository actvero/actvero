/** Convert a Retry-After header to the local clock without shortening the wait. */
export function retryAfterUntil(
  value: string | null,
  serverDate: string | null,
  receivedAt = Date.now()
): number | undefined {
  if (!value?.trim()) return undefined
  const header = value.trim()
  let delay: number
  if (/^\d+$/.test(header)) {
    const seconds = Number(header)
    if (!Number.isSafeInteger(seconds)) return undefined
    delay = seconds * 1000
  } else {
    // Date.parse alone accepts non-HTTP inputs such as negative integers.
    if (!/GMT$/i.test(header)) return undefined
    const target = Date.parse(header)
    if (!Number.isFinite(target)) return undefined
    const server = serverDate ? Date.parse(serverDate) : NaN
    delay = Math.max(
      0,
      target - (Number.isFinite(server) ? server : receivedAt)
    )
  }
  const deadline = receivedAt + delay
  return Number.isSafeInteger(deadline) && deadline <= 8.64e15
    ? deadline
    : undefined
}
