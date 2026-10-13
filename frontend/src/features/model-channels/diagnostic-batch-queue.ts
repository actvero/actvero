import { ApiError } from '@/lib/api'
import { diagnosticFormSchema } from './diagnostic-form'
import {
  diagnosticBody,
  type DiagnosticLookup,
  type DiagnosticValues,
  type DiagnosticView,
} from './diagnostic-request'
import type { Detail } from './shared'

type BatchOperation = 'chat' | 'embedding' | 'rerank'
export type BatchItemStatus =
  | 'queued'
  | 'sending'
  | 'success'
  | 'failure'
  | 'unknown'
  | 'stopped'
export type BatchState =
  | 'ready'
  | 'running'
  | 'paused'
  | 'frozen'
  | 'stopped'
  | 'done'
  | 'forbidden'

export type BatchItem = {
  index: number
  modelId: string
  operation: BatchOperation
  requestId: string | null
  status: BatchItemStatus
  result: DiagnosticView | null
  record: DiagnosticLookup | null
  error: string | null
}

export type BatchSnapshot = {
  state: BatchState
  items: BatchItem[]
  resumeAt: number | null
  localWaitUntil: number | null
  refreshRequired: boolean
  reason: string | null
}

export type BatchQueueOptions = {
  channel: Detail
  items: DiagnosticValues[]
  send: (
    body: ReturnType<typeof diagnosticBody>,
    signal: AbortSignal
  ) => Promise<DiagnosticView>
  lookup: (requestId: string, signal: AbortSignal) => Promise<DiagnosticLookup>
}

const WINDOW_MS = 60_000
const WINDOW_LIMIT = 10
const MAX_ITEMS = 50
const finished = (status: BatchItemStatus) =>
  status !== 'queued' && status !== 'sending'

function retryAt(error: unknown, now: number): number {
  if (
    error instanceof ApiError &&
    'retryAfterUntil' in error &&
    typeof error.retryAfterUntil === 'number' &&
    Number.isFinite(error.retryAfterUntil)
  )
    return Math.max(now, error.retryAfterUntil)
  return now + WINDOW_MS
}

function upstreamRetryAt(result: DiagnosticView, now: number): number {
  const seconds = result.attempt?.retry_after_seconds
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0
    ? now + seconds * 1000
    : now + WINDOW_MS
}

function isUpstream429(result: DiagnosticView): boolean {
  return Number(result.attempt?.upstream_status) === 429
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '诊断失败'
}

function aborted(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

export class DiagnosticBatchQueue {
  private readonly channel: Detail
  private readonly send: BatchQueueOptions['send']
  private readonly lookup: BatchQueueOptions['lookup']
  private values: DiagnosticValues[]
  private snapshot: BatchSnapshot
  private readonly listeners = new Set<() => void>()
  private readonly active = new Map<number, AbortController>()
  private readonly reads = new Map<number, AbortController>()
  private readonly sentAt: number[] = []
  private timer: ReturnType<typeof setTimeout> | null = null
  private disposed = false

  constructor({ channel, items, send, lookup }: BatchQueueOptions) {
    if (!items.length || items.length > MAX_ITEMS)
      throw new Error('每批须选择 1 至 50 项')
    if (channel.archived || !Number.isInteger(channel.version))
      throw new Error('渠道已归档或版本无效')
    const keys = new Set<string>()
    const rows: BatchItem[] = []
    for (const [index, input] of items.entries()) {
      const parsed = diagnosticFormSchema.safeParse(input)
      if (!parsed.success) throw new Error(`第 ${index + 1} 项参数无效`)
      const values = parsed.data
      if (
        values.operation !== 'chat' &&
        values.operation !== 'embedding' &&
        values.operation !== 'rerank'
      )
        throw new Error('批量仅支持普通对话、向量和重排诊断')
      if (!channel.models.some((model) => model.id === values.id))
        throw new Error(`第 ${index + 1} 项上游模型未登记`)
      const key = JSON.stringify([values.id, values.operation])
      if (keys.has(key)) throw new Error('同一上游模型和操作不可重复选择')
      keys.add(key)
      rows.push({
        index,
        modelId: values.id,
        operation: values.operation,
        requestId: null,
        status: 'queued',
        result: null,
        record: null,
        error: null,
      })
    }
    this.channel = { ...channel, version: channel.version }
    this.send = send
    this.lookup = lookup
    this.values = items.map((item) => ({ ...item }))
    this.snapshot = {
      state: 'ready',
      items: rows,
      resumeAt: null,
      localWaitUntil: null,
      refreshRequired: false,
      reason: null,
    }
  }

  getSnapshot = (): BatchSnapshot => this.snapshot

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private update(change: Partial<BatchSnapshot>) {
    if (this.disposed) return
    this.snapshot = { ...this.snapshot, ...change }
    for (const listener of this.listeners) listener()
  }

  private row(index: number, change: Partial<BatchItem>) {
    const rows = this.snapshot.items.slice()
    rows[index] = { ...rows[index], ...change }
    this.update({ items: rows })
  }

  private clearTimer() {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }

  start() {
    if (this.disposed || this.snapshot.state !== 'ready') return
    this.update({ state: 'running' })
    this.pump()
  }

  resume() {
    if (
      this.disposed ||
      this.snapshot.state !== 'paused' ||
      this.snapshot.resumeAt === null ||
      Date.now() < this.snapshot.resumeAt
    )
      return
    this.update({
      state: 'running',
      resumeAt: null,
      localWaitUntil: null,
      reason: null,
    })
    this.pump()
  }

  stop() {
    if (
      this.disposed ||
      !['running', 'paused', 'frozen'].includes(this.snapshot.state)
    )
      return
    this.clearTimer()
    const rows = this.snapshot.items.map((item) =>
      item.status === 'queued'
        ? { ...item, status: 'stopped' as const }
        : item.status === 'sending'
          ? {
              ...item,
              status: 'unknown' as const,
              error: '已停止等待，请按请求号回查',
            }
          : item
    )
    this.update({
      state: 'stopped',
      items: rows,
      resumeAt: null,
      localWaitUntil: null,
    })
    for (const controller of this.active.values()) controller.abort()
  }

  dispose() {
    if (this.disposed) return
    this.stop()
    this.update({
      localWaitUntil: null,
      items: this.snapshot.items.map((item) => ({
        ...item,
        result: null,
        record: null,
        error: null,
      })),
    })
    this.disposed = true
    this.clearTimer()
    for (const controller of this.active.values()) controller.abort()
    for (const controller of this.reads.values()) controller.abort()
    this.values = []
    this.listeners.clear()
  }

  private pump() {
    if (this.disposed || this.snapshot.state !== 'running') return
    const now = Date.now()
    while (this.sentAt.length && this.sentAt[0] <= now - WINDOW_MS)
      this.sentAt.shift()
    while (this.active.size < 2) {
      const next = this.snapshot.items.find((item) => item.status === 'queued')
      if (!next) break
      if (this.sentAt.length >= WINDOW_LIMIT) {
        const until = this.sentAt[0] + WINDOW_MS
        const wait = Math.max(1, until - Date.now())
        this.clearTimer()
        this.update({ localWaitUntil: until })
        this.timer = setTimeout(() => {
          this.timer = null
          this.update({ localWaitUntil: null })
          this.pump()
        }, wait)
        return
      }
      this.dispatch(next.index)
    }
    if (
      !this.active.size &&
      this.snapshot.items.every((item) => finished(item.status))
    )
      this.update({ state: 'done', localWaitUntil: null })
  }

  private dispatch(index: number) {
    const requestId = crypto.randomUUID()
    const controller = new AbortController()
    this.active.set(index, controller)
    this.sentAt.push(Date.now())
    this.row(index, { requestId, status: 'sending' })
    const body = diagnosticBody(this.channel, this.values[index], requestId)
    let request: Promise<DiagnosticView>
    try {
      request = this.send(body, controller.signal)
    } catch (error) {
      request = Promise.reject(error)
    }
    void request
      .then((result) => {
        if (this.disposed || this.snapshot.items[index].status !== 'sending')
          return
        if (isUpstream429(result)) {
          this.row(index, { result, status: 'failure' })
          this.pause(upstreamRetryAt(result, Date.now()), '上游限流')
        } else {
          this.row(index, {
            result,
            status: result.ok
              ? 'success'
              : result.uncertain
                ? 'unknown'
                : 'failure',
          })
        }
      })
      .catch((error: unknown) => {
        if (this.disposed) return
        if (error instanceof ApiError && error.status === 403) {
          this.forbid()
          return
        }
        if (this.snapshot.items[index].status !== 'sending') return
        if (error instanceof ApiError && error.status === 409) {
          this.row(index, { status: 'unknown', error: message(error) })
          this.clearTimer()
          this.update({
            state: 'frozen',
            refreshRequired: true,
            localWaitUntil: null,
            reason: '配置已变化，请回查已发项并刷新渠道',
          })
        } else if (error instanceof ApiError && error.status === 429) {
          this.row(index, { status: 'failure', error: message(error) })
          this.pause(retryAt(error, Date.now()), '请求受限')
        } else {
          this.row(index, {
            status:
              aborted(error) ||
              !(error instanceof ApiError) ||
              error.status >= 500
                ? 'unknown'
                : 'failure',
            error: message(error),
          })
        }
      })
      .finally(() => {
        this.active.delete(index)
        if (
          this.snapshot.state === 'paused' &&
          !this.active.size &&
          this.snapshot.items.every((item) => finished(item.status))
        ) {
          this.update({ state: 'done', resumeAt: null, localWaitUntil: null })
          return
        }
        this.pump()
      })
  }

  private pause(until: number, reason: string) {
    if (this.snapshot.state !== 'running' && this.snapshot.state !== 'paused')
      return
    this.clearTimer()
    this.update({
      state: 'paused',
      resumeAt: Math.max(this.snapshot.resumeAt ?? until, until),
      localWaitUntil: null,
      reason,
    })
  }

  private forbid() {
    this.clearTimer()
    for (const controller of this.active.values()) controller.abort()
    const rows = this.snapshot.items.map((item) => ({
      ...item,
      status:
        item.status === 'queued'
          ? ('stopped' as const)
          : item.status === 'sending'
            ? ('unknown' as const)
            : item.status,
      result: null,
      record: null,
      error: null,
    }))
    this.update({
      state: 'forbidden',
      items: rows,
      resumeAt: null,
      localWaitUntil: null,
      reason: '权限已失效',
    })
  }

  private cannotRead() {
    return this.disposed || this.snapshot.state === 'forbidden'
  }

  async readRecord(indexOrRequestId: number | string): Promise<void> {
    if (this.cannotRead()) return
    const index =
      typeof indexOrRequestId === 'number'
        ? indexOrRequestId
        : this.snapshot.items.findIndex(
            (item) => item.requestId === indexOrRequestId
          )
    const item = this.snapshot.items[index]
    if (!item?.requestId || item.status === 'sending' || this.reads.has(index))
      return
    const controller = new AbortController()
    this.reads.set(index, controller)
    try {
      const found = await this.lookup(item.requestId, controller.signal)
      if (
        this.cannotRead() ||
        found.channel_id !== this.channel.id ||
        found.record.request_id !== item.requestId
      )
        return
      this.row(index, {
        record: found,
        status:
          found.record.status === 'success'
            ? 'success'
            : found.record.status === 'failure' && !found.record.uncertain
              ? 'failure'
              : 'unknown',
        error: null,
      })
    } catch (error) {
      if (this.cannotRead()) return
      if (error instanceof ApiError && error.status === 403) this.forbid()
      else this.row(index, { error: message(error) })
    } finally {
      this.reads.delete(index)
    }
  }
}

export function createDiagnosticBatchQueue(options: BatchQueueOptions) {
  return new DiagnosticBatchQueue(options)
}
