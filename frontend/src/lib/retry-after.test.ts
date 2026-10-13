import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { retryAfterUntil } from './retry-after'

afterEach(() => vi.unstubAllGlobals())
const now = Date.parse('2026-10-04T00:00:00Z')
it('keeps long delta seconds and zero without imposing a one-hour cap', () => {
  expect(retryAfterUntil('7200', null, now)).toBe(now + 7200000)
  expect(retryAfterUntil('0', null, now)).toBe(now)
})
it('accounts for server/client clock differences on HTTP-date waits', () => {
  expect(
    retryAfterUntil(
      'Sun, 04 Oct 2026 04:00:00 GMT',
      'Sun, 04 Oct 2026 02:00:00 GMT',
      now
    )
  ).toBe(now + 7200000)
  expect(retryAfterUntil('Sun, 04 Oct 2026 01:00:00 GMT', null, now)).toBe(
    now + 3600000
  )
  expect(retryAfterUntil('Sat, 03 Oct 2026 23:00:00 GMT', null, now)).toBe(now)
})
it.each([null, '', '-1', '1.5', 'bad', '999999999999999999999'])(
  'ignores invalid Retry-After %s',
  (value) => {
    expect(retryAfterUntil(value, null, now)).toBeUndefined()
  }
)
it('keeps the response wait with API errors without exposing response headers', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        { error: { message: '限流' } },
        {
          status: 429,
          headers: { 'Retry-After': '7200' },
        }
      )
    )
  )
  const before = Date.now()
  try {
    await api('/llm/channels/example/diagnostics', 'POST', {}, 'fixture')
    expect.fail('Expected rate limit')
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(429)
    expect((error as ApiError).retryAfterUntil).toBeGreaterThanOrEqual(
      before + 7200000
    )
  }
})
