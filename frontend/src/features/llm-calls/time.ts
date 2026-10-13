/** Render the same absolute instant in the selected, explicitly displayed IANA timezone. */
export function timeInZone(value: string, timezone: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: timezone || 'UTC',
    dateStyle: 'short',
    timeStyle: 'medium',
    hour12: false,
  }).format(new Date(value))
}
