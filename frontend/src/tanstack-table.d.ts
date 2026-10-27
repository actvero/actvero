import '@tanstack/react-table'

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    mobileTitle?: boolean
    mobileBadge?: boolean
    mobileHidden?: boolean
    mobileOrder?: number
    label?: string
    pinned?: 'left' | 'right'
    className?: string // apply to both th and td
    tdClassName?: string
    thClassName?: string
  }
}
