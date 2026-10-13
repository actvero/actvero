import { describe, expect, it, vi } from 'vitest'
import {
  filterSchema,
  queryFor,
  zonedMinuteToIso,
  type Filters,
} from './filters'
import { readCallSearch, searchFromFilters, searchToFilters } from './search'

const id = '69fc6575-7066-4bd1-a4f7-0a8705ee6d71'

function values(overrides: Partial<Filters> = {}): Filters {
  return {
    fromLocal: '2026-01-01T00:00',
    toLocal: '2026-04-01T00:00',
    timezone: 'UTC',
    member_id: '',
    model_id: '',
    operation: '',
    source: 'member',
    result_status: '',
    settlement_status: '',
    call_id: '',
    held: false,
    ...overrides,
  }
}

describe('local billing time', () => {
  it('rejects nonexistent and repeated DST minutes without silently shifting them', () => {
    expect(zonedMinuteToIso('2026-03-08T02:30', 'America/New_York')).toBeNull()
    expect(zonedMinuteToIso('2026-11-01T01:30', 'America/New_York')).toBeNull()
    expect(zonedMinuteToIso('2026-03-08T01:30', 'America/New_York')).toBe(
      '2026-03-08T06:30:00.000Z'
    )
    expect(zonedMinuteToIso('2026-03-08T03:30', 'America/New_York')).toBe(
      '2026-03-08T07:30:00.000Z'
    )
    expect(zonedMinuteToIso('2026-10-04T08:30', 'Asia/Shanghai')).toBe(
      '2026-10-04T00:30:00.000Z'
    )
    expect(zonedMinuteToIso('2026-02-30T12:00', 'UTC')).toBeNull()
  })

  it('requires paired aware bounds and accepts exactly ninety days, not longer', () => {
    expect(filterSchema().safeParse(values()).success).toBe(true)
    expect(
      filterSchema().safeParse(values({ toLocal: '2026-04-01T00:01' })).success
    ).toBe(false)
    expect(
      filterSchema().safeParse(values({ toLocal: '2026-01-01T00:00' })).success
    ).toBe(false)
    expect(filterSchema().safeParse(values({ fromLocal: '' })).success).toBe(
      false
    )
    expect(filterSchema().safeParse(values({ toLocal: '' })).success).toBe(
      false
    )
    expect(
      filterSchema().safeParse(values({ fromLocal: '', toLocal: '' })).success
    ).toBe(true)
    expect(
      filterSchema(true).safeParse(values({ fromLocal: '', toLocal: '' }))
        .success
    ).toBe(false)
    expect(
      filterSchema().safeParse(
        values({
          fromLocal: '2026-03-08T02:30',
          toLocal: '2026-03-08T03:30',
          timezone: 'America/New_York',
        })
      ).success
    ).toBe(false)
  })
})

describe('shareable call filters', () => {
  it('leaves call-list dates empty while statistics alone default to seven days', () => {
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-10-04T00:30:00.000Z'))
      const search = readCallSearch({ timezone: 'Asia/Shanghai' })
      const list = searchToFilters(search)
      expect(list.fromLocal).toBe('')
      expect(list.toLocal).toBe('')
      const listQuery = new URLSearchParams(queryFor(list))
      expect(listQuery.has('from')).toBe(false)
      expect(listQuery.has('to')).toBe(false)

      const summary = searchToFilters(search, true)
      expect(summary.fromLocal).toBe('2026-09-27T08:30')
      expect(summary.toLocal).toBe('2026-10-04T08:30')
      const summaryQuery = new URLSearchParams(queryFor(summary, 1, true))
      expect(summaryQuery.get('from')).toBe('2026-09-27T00:30:00.000Z')
      expect(summaryQuery.get('to')).toBe('2026-10-04T00:30:00.000Z')
      expect(summaryQuery.get('source')).toBe('member')
      expect(
        searchToFilters(readCallSearch({ held: true }), true)
      ).toMatchObject({
        fromLocal: '',
        toLocal: '',
        held: true,
      })
    } finally {
      vi.useRealTimers()
    }
  })

  it('retains exact aware instants from URL offsets through the query', () => {
    const search = readCallSearch({
      from: '2026-10-01T08:00:00+08:00',
      to: '2026-10-02T04:00:00-04:00',
      timezone: 'Asia/Shanghai',
      source: 'access_key',
      call_id: id,
      page: '2',
    })
    expect(search.from).toBe('2026-10-01T00:00:00.000Z')
    expect(search.to).toBe('2026-10-02T08:00:00.000Z')
    const query = new URLSearchParams(queryFor(searchToFilters(search), 2))
    expect(query.get('from')).toBe(search.from)
    expect(query.get('to')).toBe(search.to)
    expect(query.get('source')).toBe('access_key')
    expect(query.get('call_id')).toBe(id)
    expect(query.get('page')).toBe('2')
    expect(readCallSearch({ from: '2026-10-01T08:00:00' }).from).toBe('')
  })

  it('keeps a held link scoped while removing old range, status, and call ID', () => {
    const held = readCallSearch({
      held: 'true',
      from: '2026-10-01T00:00:00Z',
      to: '2026-10-02T00:00:00Z',
      source: 'desktop',
      member_id: id,
      operation: 'chat',
      result_status: 'failed',
      settlement_status: 'settled',
      call_id: id,
    })
    expect(held).toMatchObject({
      from: '',
      to: '',
      source: 'desktop',
      member_id: id,
      operation: 'chat',
      result_status: '',
      settlement_status: '',
      call_id: '',
      held: true,
    })
    const query = new URLSearchParams(queryFor(searchToFilters(held)))
    expect(query.get('held')).toBe('true')
    expect(query.get('source')).toBe('desktop')
    for (const forbidden of [
      'from',
      'to',
      'result_status',
      'settlement_status',
      'call_id',
    ]) {
      expect(query.has(forbidden)).toBe(false)
    }
    expect(readCallSearch({ held: true, source: 'diagnostic' }).source).toBe(
      'member'
    )
    expect(readCallSearch({ held: true, source: 'all' }).source).toBe('member')
  })

  it('keeps the selected source and independent result/settlement filters', () => {
    const filters = values({
      source: 'diagnostic',
      result_status: 'success',
      settlement_status: 'not_applicable',
      operation: 'embedding',
      call_id: id,
    })
    const query = new URLSearchParams(queryFor(filters, 3))
    expect(query.get('source')).toBe('diagnostic')
    expect(query.get('result_status')).toBe('success')
    expect(query.get('settlement_status')).toBe('not_applicable')
    expect(query.get('operation')).toBe('embedding')
    expect(query.get('call_id')).toBe(id)
    expect(query.get('page')).toBe('3')
    const roundTrip = searchFromFilters(filters, 3)
    expect(roundTrip.source).toBe('diagnostic')
    expect(roundTrip.result_status).toBe('success')
    expect(roundTrip.settlement_status).toBe('not_applicable')
    expect(roundTrip.page).toBe(3)
  })
})
