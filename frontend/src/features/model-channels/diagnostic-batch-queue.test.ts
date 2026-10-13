import { afterEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import {
  createDiagnosticBatchQueue,
  type BatchQueueOptions,
} from './diagnostic-batch-queue'
import type {
  DiagnosticLookup,
  DiagnosticValues,
  DiagnosticView,
} from './diagnostic-request'
import type { Detail } from './shared'

const channel = {
  id: 'channel-a',
  version: 7,
  archived: false,
  models: Array.from({ length: 55 }, (_, index) => ({ id: `model-${index}` })),
} as Detail

const values = (
  index: number,
  operation: 'chat' | 'embedding' | 'rerank' = 'chat'
): DiagnosticValues => ({
  id: `model-${index}`,
  operation,
  texts: operation === 'rerank' ? '北京\n上海' : '你好',
  query: operation === 'rerank' ? '首都' : '',
  count: operation === 'chat' ? '64' : '',
  voice: '',
  size: '',
  quality: '',
})

const outcome = (
  requestId: string,
  ok = true,
  attempt: Record<string, unknown> = {}
) =>
  ({
    request_id: requestId,
    ok,
    attempt,
    operation: 'chat',
    duration_ms: 1,
    message: '',
    output: '',
    health_certification: 'not_requested',
  }) as DiagnosticView

const record = (
  requestId: string,
  status: 'success' | 'failure' | 'unconfirmed'
): DiagnosticLookup => ({
  channel_id: channel.id,
  media_available: false,
  record: {
    request_id: requestId,
    status,
    operation: 'chat',
    model: 'model-0',
    tested_at: new Date().toISOString(),
    uncertain: status === 'unconfirmed',
    stale: false,
    record_version: 'attempt_v1',
    health_certification: 'not_requested',
  },
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function setup(items: DiagnosticValues[], send?: BatchQueueOptions['send']) {
  const calls: Array<{
    body: Parameters<BatchQueueOptions['send']>[0]
    signal: AbortSignal
    pending: ReturnType<typeof deferred<DiagnosticView>>
  }> = []
  const sender: BatchQueueOptions['send'] =
    send ??
    ((body, signal) => {
      const pending = deferred<DiagnosticView>()
      calls.push({ body, signal, pending })
      return pending.promise
    })
  const lookup = vi.fn<BatchQueueOptions['lookup']>()
  const queue = createDiagnosticBatchQueue({
    channel,
    items,
    send: sender,
    lookup,
  })
  return { queue, calls, lookup }
}

async function settle() {
  for (let index = 0; index < 40; index++) await Promise.resolve()
}

afterEach(() => {
  vi.useRealTimers()
})

it('rejects invalid, duplicate, media, unknown model, and over-50 selections before dispatch', () => {
  const send = vi.fn()
  const make = (items: DiagnosticValues[]) =>
    createDiagnosticBatchQueue({ channel, items, send, lookup: vi.fn() })
  expect(() => make([])).toThrow()
  expect(() =>
    make(Array.from({ length: 51 }, (_, index) => values(index)))
  ).toThrow()
  expect(() => make([values(0), values(0)])).toThrow()
  expect(() => make([{ ...values(0), texts: '' }])).toThrow()
  expect(() => make([{ ...values(0), id: 'not-registered' }])).toThrow()
  expect(() =>
    make([{ ...values(0), operation: 'image_generation' }])
  ).toThrow()
  expect(() => make([{ ...values(0, 'rerank'), query: '' }])).toThrow()
  expect(send).not.toHaveBeenCalled()
  expect(
    make(Array.from({ length: 50 }, (_, index) => values(index))).getSnapshot()
      .items
  ).toHaveLength(50)
})

it('dispatches at most two at once with unique IDs and versioned non-certifying bodies', async () => {
  const { queue, calls } = setup([
    values(0),
    values(1, 'embedding'),
    values(2, 'rerank'),
  ])
  const changed = vi.fn()
  const unsubscribe = queue.subscribe(changed)
  queue.start()
  expect(calls).toHaveLength(2)
  expect(calls[0].body).toMatchObject({
    version: 7,
    operation: 'chat',
    endpoint: 'chat_completions',
    stream: false,
    certify_health: false,
  })
  expect(calls[1].body).toMatchObject({
    operation: 'embedding',
    endpoint: 'embeddings',
    input: { input: ['你好'] },
  })
  expect(calls[0].body.request_id).not.toBe(calls[1].body.request_id)
  expect(queue.getSnapshot().items[2].status).toBe('queued')
  calls[0].pending.resolve(outcome(calls[0].body.request_id))
  await settle()
  expect(calls).toHaveLength(3)
  expect(calls[2].body).toMatchObject({
    operation: 'rerank',
    endpoint: 'rerank',
    input: { query: '首都', documents: ['北京', '上海'] },
  })
  expect(new Set(calls.map((call) => call.body.request_id)).size).toBe(3)
  calls[1].pending.resolve(outcome(calls[1].body.request_id, false))
  calls[2].pending.resolve(outcome(calls[2].body.request_id))
  await settle()
  expect(queue.getSnapshot().state).toBe('done')
  expect(queue.getSnapshot().items.map((item) => item.status)).toEqual([
    'success',
    'failure',
    'success',
  ])
  const stable = queue.getSnapshot()
  expect(queue.getSnapshot()).toBe(stable)
  unsubscribe()
  expect(changed).toHaveBeenCalled()
})

it('locally throttles the eleventh POST until the rolling 60-second slot opens', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(1_000_000)
  const send = vi.fn<BatchQueueOptions['send']>((body) =>
    Promise.resolve(outcome(body.request_id))
  )
  const { queue } = setup(
    Array.from({ length: 12 }, (_, index) => values(index)),
    send
  )
  queue.start()
  await settle()
  expect(send).toHaveBeenCalledTimes(10)
  expect(queue.getSnapshot().state).toBe('running')
  expect(queue.getSnapshot().localWaitUntil).toBe(1_060_000)
  await vi.advanceTimersByTimeAsync(59_999)
  expect(send).toHaveBeenCalledTimes(10)
  expect(queue.getSnapshot().localWaitUntil).toBe(1_060_000)
  await vi.advanceTimersByTimeAsync(1)
  await settle()
  expect(send).toHaveBeenCalledTimes(12)
  expect(queue.getSnapshot().localWaitUntil).toBeNull()
  expect(queue.getSnapshot().state).toBe('done')
  queue.dispose()
})

it.each([403, 409, 429])(
  'clears the local wait when an active request receives HTTP %s',
  async (status) => {
    vi.useFakeTimers()
    vi.setSystemTime(4_000_000)
    const pending = deferred<DiagnosticView>()
    let sent = 0
    const send = vi.fn<BatchQueueOptions['send']>((body) => {
      sent += 1
      return sent === 10
        ? pending.promise
        : Promise.resolve(outcome(body.request_id))
    })
    const { queue } = setup(
      Array.from({ length: 12 }, (_, index) => values(index)),
      send
    )
    queue.start()
    await settle()
    expect(send).toHaveBeenCalledTimes(10)
    expect(queue.getSnapshot().localWaitUntil).toBe(4_060_000)
    pending.reject(new ApiError(status, 'stopped'))
    await settle()
    expect(queue.getSnapshot().localWaitUntil).toBeNull()
    expect(queue.getSnapshot().state).toBe(
      status === 403 ? 'forbidden' : status === 409 ? 'frozen' : 'paused'
    )
    queue.dispose()
  }
)

it('clears the local wait when stopped or disposed', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(5_000_000)
  const send = vi.fn<BatchQueueOptions['send']>((body) =>
    Promise.resolve(outcome(body.request_id))
  )
  const { queue } = setup(
    Array.from({ length: 12 }, (_, index) => values(index)),
    send
  )
  queue.start()
  await settle()
  expect(queue.getSnapshot().localWaitUntil).toBe(5_060_000)
  queue.stop()
  expect(queue.getSnapshot().localWaitUntil).toBeNull()
  queue.dispose()
  await vi.advanceTimersByTimeAsync(60_000)
  expect(send).toHaveBeenCalledTimes(10)
})

it('pauses on an upstream 429 and needs explicit resume after its retry time', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(1_000_000)
  const { queue, calls } = setup([values(0), values(1), values(2)])
  queue.start()
  calls[0].pending.resolve(
    outcome(calls[0].body.request_id, false, {
      upstream_status: 429,
      retry_after_seconds: 5,
    })
  )
  await settle()
  expect(queue.getSnapshot()).toMatchObject({
    state: 'paused',
    resumeAt: 1_005_000,
  })
  calls[1].pending.resolve(outcome(calls[1].body.request_id))
  await settle()
  queue.resume()
  expect(calls).toHaveLength(2)
  await vi.advanceTimersByTimeAsync(5_000)
  expect(calls).toHaveLength(2)
  queue.resume()
  expect(calls).toHaveLength(3)
  expect(queue.getSnapshot().items[0].status).toBe('failure')
  calls[2].pending.resolve(outcome(calls[2].body.request_id))
  await settle()
  expect(queue.getSnapshot().state).toBe('done')
})

it('keeps the longest deadline when both active calls return 429', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(3_000_000)
  const { queue, calls } = setup([
    values(0),
    values(1),
    values(2),
    values(3),
    values(4),
  ])
  queue.start()
  calls[0].pending.resolve(
    outcome(calls[0].body.request_id, false, {
      upstream_status: 429,
      retry_after_seconds: 5,
    })
  )
  await settle()
  calls[1].pending.resolve(
    outcome(calls[1].body.request_id, false, {
      upstream_status: 429,
      retry_after_seconds: 20,
    })
  )
  await settle()
  expect(queue.getSnapshot().resumeAt).toBe(3_020_000)
  await vi.advanceTimersByTimeAsync(5_000)
  queue.resume()
  expect(calls).toHaveLength(2)
  await vi.advanceTimersByTimeAsync(15_000)
  queue.resume()
  expect(calls).toHaveLength(4)
  calls[2].pending.resolve(
    outcome(calls[2].body.request_id, false, {
      upstream_status: 429,
      retry_after_seconds: 0,
    })
  )
  await settle()
  expect(queue.getSnapshot().resumeAt).toBe(3_020_000)
  expect(calls).toHaveLength(4)
  queue.stop()
})

it('uses an HTTP 429 retry deadline and never resends that item', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(2_000_000)
  const { queue, calls } = setup([values(0), values(1), values(2)])
  queue.start()
  const error = new ApiError(429, 'limited') as ApiError & {
    retryAfterUntil: number
  }
  error.retryAfterUntil = 2_015_000
  calls[0].pending.reject(error)
  await settle()
  expect(queue.getSnapshot().resumeAt).toBe(2_015_000)
  expect(queue.getSnapshot().items[0].status).toBe('failure')
  queue.stop()
  expect(calls).toHaveLength(2)
})

it('stops queued work, aborts both active calls, and preserves their IDs as unknown', async () => {
  const { queue, calls } = setup([values(0), values(1), values(2)])
  queue.start()
  const ids = calls.map((call) => call.body.request_id)
  queue.stop()
  expect(queue.getSnapshot().state).toBe('stopped')
  expect(queue.getSnapshot().items.map((item) => item.status)).toEqual([
    'unknown',
    'unknown',
    'stopped',
  ])
  expect(calls.every((call) => call.signal.aborted)).toBe(true)
  calls[0].pending.resolve(outcome(ids[0]))
  calls[1].pending.resolve(outcome(ids[1]))
  await settle()
  expect(
    queue
      .getSnapshot()
      .items.slice(0, 2)
      .map((item) => item.requestId)
  ).toEqual(ids)
  expect(queue.getSnapshot().items[0].status).toBe('unknown')
  expect(calls).toHaveLength(2)
})

it('disposes without dispatching more work or retaining response data', async () => {
  const { queue, calls } = setup([values(0), values(1), values(2)])
  queue.start()
  queue.dispose()
  calls[0].pending.resolve(outcome(calls[0].body.request_id))
  await settle()
  expect(calls).toHaveLength(2)
  expect(queue.getSnapshot().items[2].status).toBe('stopped')
  queue.start()
  expect(calls).toHaveLength(2)
})

it('a 403 stops unsent work and clears all displayed results', async () => {
  const { queue, calls } = setup([values(0), values(1), values(2), values(3)])
  queue.start()
  calls[0].pending.resolve(outcome(calls[0].body.request_id))
  await settle()
  expect(queue.getSnapshot().items[0].result).not.toBeNull()
  expect(calls).toHaveLength(3)
  calls[1].pending.reject(new ApiError(403, 'forbidden'))
  await settle()
  expect(queue.getSnapshot().state).toBe('forbidden')
  expect(
    queue
      .getSnapshot()
      .items.every((item) => item.result === null && item.record === null)
  ).toBe(true)
  expect(calls[2].signal.aborted).toBe(true)
  expect(calls).toHaveLength(3)
})

it('a late 403 after stop still erases earlier displayed results', async () => {
  const { queue, calls } = setup([values(0), values(1), values(2)])
  queue.start()
  calls[0].pending.resolve(outcome(calls[0].body.request_id))
  await settle()
  expect(queue.getSnapshot().items[0].result).not.toBeNull()
  queue.stop()
  calls[1].pending.reject(new ApiError(403, 'forbidden'))
  await settle()
  expect(queue.getSnapshot().state).toBe('forbidden')
  expect(queue.getSnapshot().items.every((item) => item.result === null)).toBe(
    true
  )
})

it('a 409 freezes remaining work and preserves its request ID for GET', async () => {
  const { queue, calls, lookup } = setup([values(0), values(1), values(2)])
  queue.start()
  const id = calls[0].body.request_id
  calls[0].pending.reject(new ApiError(409, 'changed'))
  await settle()
  expect(queue.getSnapshot().state).toBe('frozen')
  expect(queue.getSnapshot().items[0]).toMatchObject({
    status: 'unknown',
    requestId: id,
  })
  calls[1].pending.resolve(outcome(calls[1].body.request_id))
  await settle()
  expect(calls).toHaveLength(2)
  lookup.mockResolvedValue(record(id, 'success'))
  await queue.readRecord(id)
  expect(lookup).toHaveBeenCalledWith(id, expect.any(AbortSignal))
  expect(queue.getSnapshot().items[0].status).toBe('success')
  expect(calls).toHaveLength(2)
  queue.stop()
  expect(queue.getSnapshot().refreshRequired).toBe(true)
  expect(queue.getSnapshot().state).toBe('stopped')
})

it('network and 5xx ambiguity can be queried by original ID without a second POST', async () => {
  const { queue, calls, lookup } = setup([values(0), values(1)])
  queue.start()
  calls[0].pending.reject(new TypeError('network lost'))
  calls[1].pending.reject(new ApiError(503, 'upstream unavailable'))
  await settle()
  expect(queue.getSnapshot().items.map((item) => item.status)).toEqual([
    'unknown',
    'unknown',
  ])
  lookup.mockImplementation((id) =>
    Promise.resolve(
      record(id, id === calls[0].body.request_id ? 'unconfirmed' : 'failure')
    )
  )
  await queue.readRecord(0)
  await queue.readRecord(1)
  expect(queue.getSnapshot().items.map((item) => item.status)).toEqual([
    'unknown',
    'failure',
  ])
  expect(calls).toHaveLength(2)
  expect(queue.getSnapshot().state).toBe('done')
})

it('does not let a GET race replace a sending POST outcome', async () => {
  const { queue, calls, lookup } = setup([values(0)])
  queue.start()
  await queue.readRecord(0)
  expect(lookup).not.toHaveBeenCalled()
  calls[0].pending.resolve(outcome(calls[0].body.request_id))
  await settle()
  expect(queue.getSnapshot().items[0].status).toBe('success')
})

it('keeps accepted timeout uncertainty in both the result and metadata lookup', async () => {
  const { queue, calls, lookup } = setup([values(0)])
  queue.start()
  const id = calls[0].body.request_id
  calls[0].pending.resolve({ ...outcome(id, false), uncertain: true })
  await settle()
  expect(queue.getSnapshot().items[0].status).toBe('unknown')
  const found = record(id, 'failure')
  found.record.uncertain = true
  lookup.mockResolvedValue(found)
  await queue.readRecord(id)
  expect(queue.getSnapshot().items[0].status).toBe('unknown')
  expect(calls).toHaveLength(1)
  expect(queue.getSnapshot().state).toBe('done')
})
