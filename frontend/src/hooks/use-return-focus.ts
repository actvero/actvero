import { useState } from 'react'

/** Restore the opener when a controlled dialog is mounted without a Radix trigger. */
export function useReturnFocus(fallback?: () => void) {
  const [target] = useState(() => document.activeElement)
  return (event: Event) => {
    event.preventDefault()
    if (fallback) fallback()
    else if (target instanceof HTMLElement && target.isConnected) target.focus()
  }
}
