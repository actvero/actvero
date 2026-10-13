import type { ReactNode } from 'react'

/** Keep comparable metrics on one desktop row; scroll inside the row when needed. */
export function MetricGrid({
  children,
  label,
}: {
  children: ReactNode
  label: string
}) {
  return (
    <div
      role='region'
      aria-label={label}
      tabIndex={0}
      className='grid min-w-0 shrink-0 grid-cols-1 gap-3 overflow-x-auto pb-2 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:auto-cols-[minmax(180px,1fr)] sm:grid-flow-col sm:grid-cols-none'
    >
      {children}
    </div>
  )
}
