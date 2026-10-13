import {
  civilAt,
  operations,
  queryFor,
  results,
  settlements,
  sources,
  type Filters,
} from './filters'

export type CallSearch = {
  channel_id?: string
  unknown_channel?: boolean
  from: string
  to: string
  timezone: string
  member_id: string
  model_id: string
  operation: string
  source: keyof typeof sources
  result_status: string
  settlement_status: string
  call_id: string
  held: boolean
  page: number
}

function str(value: unknown) {
  return typeof value === 'string' ? value : ''
}
function pick<T extends Record<string, string>>(
  value: unknown,
  options: T,
  fallback: keyof T | ''
): keyof T | '' {
  const candidate = str(value)
  return Object.prototype.hasOwnProperty.call(options, candidate)
    ? (candidate as keyof T)
    : fallback
}
function timezone(value: unknown) {
  const candidate = str(value)
  if (!candidate) return ''
  try {
    new Intl.DateTimeFormat('en', { timeZone: candidate })
    return candidate
  } catch {
    return ''
  }
}
function awareIso(value: unknown) {
  const candidate = str(value)
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(
      candidate
    )
  )
    return ''
  const time = Date.parse(candidate)
  return Number.isFinite(time) ? new Date(time).toISOString() : ''
}

/** TanStack validateSearch entry: unknown URL values become a bounded, shareable filter state. */
export function readCallSearch(search: Record<string, unknown>): CallSearch {
  const held = search.held === true || search.held === 'true'
  const source = pick(search.source, sources, 'member') as keyof typeof sources
  const page = Number(search.page)
  return {
    channel_id: held ? '' : str(search.channel_id),
    unknown_channel:
      !held &&
      (search.unknown_channel === true || search.unknown_channel === 'true'),
    from: held ? '' : awareIso(search.from),
    to: held ? '' : awareIso(search.to),
    timezone: timezone(search.timezone),
    member_id: str(search.member_id),
    model_id: str(search.model_id),
    operation: pick(search.operation, operations, ''),
    source:
      held && (source === 'diagnostic' || source === 'all') ? 'member' : source,
    result_status: held ? '' : pick(search.result_status, results, ''),
    settlement_status: held
      ? ''
      : pick(search.settlement_status, settlements, ''),
    call_id: held ? '' : str(search.call_id),
    held,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  }
}

export function searchToFilters(
  search: CallSearch,
  defaultRange = false
): Filters {
  const zone = search.timezone || 'UTC'
  let fromLocal =
    search.held || !defaultRange
      ? ''
      : civilAt(Date.now() - 7 * 24 * 60 * 60 * 1000, zone)
  let toLocal = search.held || !defaultRange ? '' : civilAt(Date.now(), zone)
  if (search.from && search.to) {
    try {
      fromLocal = civilAt(Date.parse(search.from), zone)
      toLocal = civilAt(Date.parse(search.to), zone)
    } catch {
      /* invalid URL time zones are sanitized by readCallSearch */
    }
  }
  return {
    channel_id: search.channel_id,
    unknown_channel: search.unknown_channel,
    fromLocal,
    toLocal,
    timezone: zone,
    member_id: search.member_id,
    model_id: search.model_id,
    operation: search.operation,
    source: search.source,
    result_status: search.result_status,
    settlement_status: search.settlement_status,
    call_id: search.call_id,
    held: search.held,
  }
}

export function searchFromFilters(filters: Filters, page = 1): CallSearch {
  return readCallSearch(
    Object.fromEntries(new URLSearchParams(queryFor(filters, page)))
  )
}
