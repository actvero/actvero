import { ApiError } from '@/lib/api'
import type { DiagnosticView } from './diagnostic-request'

export type StreamProgress = {
  accepted: boolean
  content: string
  reasoning: string
  refusal: string
  tools: string[]
  usage: string | null
  truncated: boolean
}
export type StreamOutcome = {
  status: 'success' | 'failure' | 'unconfirmed'
  result: DiagnosticView
}

const MAX_EVENT = 64_000
const MAX_WIRE = 8_000_000
const MAX_OUTPUT = 32_000
const MAX_TOOLS = 16
const initialProgress = (): StreamProgress => ({
  accepted: false,
  content: '',
  reasoning: '',
  refusal: '',
  tools: [],
  usage: null,
  truncated: false,
})

export class DiagnosticStreamError extends Error {
  constructor(
    message: string,
    public status?: number,
    public uncertain = true
  ) {
    super(message)
  }
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new DiagnosticStreamError('诊断事件格式不正确，请按请求号回查。')
  return value as Record<string, unknown>
}

function appendBounded(old: string, value: unknown): [string, boolean] {
  if (typeof value !== 'string' || !value) return [old, false]
  const space = Math.max(0, MAX_OUTPUT - old.length)
  return [old + value.slice(0, space), value.length > space]
}

// The POST body and partial text live only in the caller's memory.
export async function runDiagnosticStream(
  path: string,
  body: unknown,
  csrf: string,
  requestId: string,
  signal: AbortSignal,
  update: (progress: StreamProgress) => void
): Promise<StreamOutcome> {
  const response = await fetch('/api/v1' + path, {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(
      response.status,
      error?.error?.message ?? '请求失败，请稍后重试'
    )
  }
  if (
    !response.body ||
    !response.headers.get('content-type')?.includes('text/event-stream')
  )
    throw new DiagnosticStreamError('未返回诊断事件流，请按请求号回查。')

  const reader = response.body.getReader()
  const cancelReader = () => void reader.cancel().catch(() => undefined)
  signal.addEventListener('abort', cancelReader, { once: true })
  const decoder = new TextDecoder()
  const progress = initialProgress()
  const toolNames: string[] = []
  const expectedVersion =
    body && typeof body === 'object' && 'version' in body
      ? (body as { version: unknown }).version
      : undefined
  let pending = ''
  let eventName = ''
  let dataLines: string[] = []
  let eventSize = 0
  let wireSize = 0
  let terminal: StreamOutcome | null = null
  const dispatch = () => {
    const name = eventName
    const data = dataLines.join('\n')
    eventName = ''
    dataLines = []
    eventSize = 0
    if (!name || !data || terminal) return
    let parsed: Record<string, unknown>
    try {
      parsed = object(JSON.parse(data))
    } catch {
      throw new DiagnosticStreamError('诊断事件无法解析，请按请求号回查。')
    }
    if (parsed.request_id !== requestId)
      throw new DiagnosticStreamError(
        '诊断事件请求号不匹配，请按原请求号回查。'
      )
    if (name === 'accepted') {
      if (
        progress.accepted ||
        parsed.attempt_id !== requestId ||
        parsed.operation !== 'chat' ||
        (typeof expectedVersion === 'number' &&
          parsed.channel_version !== expectedVersion)
      )
        throw new DiagnosticStreamError('诊断受理信息不匹配，请按请求号回查。')
      progress.accepted = true
    } else if (name === 'delta') {
      if (!progress.accepted)
        throw new DiagnosticStreamError('诊断事件顺序不正确，请按请求号回查。')
      const delta = object(parsed.delta)
      let clipped: boolean
      ;[progress.content, clipped] = appendBounded(
        progress.content,
        delta.content
      )
      progress.truncated ||= clipped
      ;[progress.reasoning, clipped] = appendBounded(
        progress.reasoning,
        delta.reasoning_content
      )
      progress.truncated ||= clipped
      ;[progress.refusal, clipped] = appendBounded(
        progress.refusal,
        delta.refusal
      )
      progress.truncated ||= clipped
      if (delta.tool_calls !== undefined) {
        if (!Array.isArray(delta.tool_calls))
          throw new DiagnosticStreamError(
            '工具事件格式不正确，请按请求号回查。'
          )
        for (const item of delta.tool_calls) {
          if (!item || typeof item !== 'object') continue
          const tool = item as Record<string, unknown>
          const index = tool.index
          if (
            !Number.isInteger(index) ||
            Number(index) < 0 ||
            Number(index) >= MAX_TOOLS
          ) {
            progress.truncated = true
            continue
          }
          const position = Number(index)
          const fn = tool.function
          const part =
            fn && typeof fn === 'object' && !Array.isArray(fn)
              ? (fn as Record<string, unknown>).name
              : null
          toolNames[position] =
            (toolNames[position] ?? '') +
            (typeof part === 'string' ? part.slice(0, 120) : '')
          if (toolNames[position].length > 120) {
            toolNames[position] = toolNames[position].slice(0, 120)
            progress.truncated = true
          }
        }
        progress.tools = toolNames.map((name, index) =>
          name ? `工具调用 ${index + 1}：${name}` : `工具调用 ${index + 1}`
        )
      }
    } else if (name === 'usage') {
      if (!progress.accepted)
        throw new DiagnosticStreamError('诊断事件顺序不正确，请按请求号回查。')
      const input = parsed.input_tokens
      const output = parsed.output_tokens
      progress.usage =
        parsed.usage_source === 'upstream' &&
        Number.isSafeInteger(input) &&
        Number(input) >= 0 &&
        Number.isSafeInteger(output) &&
        Number(output) >= 0
          ? `上游用量：输入 ${input}、输出 ${output} Token`
          : '上游尚未返回完整用量'
    } else if (name === 'result') {
      if (!progress.accepted)
        throw new DiagnosticStreamError('诊断缺少受理事件，请按请求号回查。')
      const status = parsed.status
      const result = object(parsed.result) as DiagnosticView
      if (
        (status !== 'success' &&
          status !== 'failure' &&
          status !== 'unconfirmed') ||
        result.request_id !== requestId ||
        result.operation !== 'chat' ||
        result.stream !== true ||
        typeof result.ok !== 'boolean' ||
        (status === 'success' &&
          (!result.ok ||
            result.uncertain !== false ||
            result.attempt?.upstream_terminal !== true)) ||
        (status !== 'success' && result.ok)
      )
        throw new DiagnosticStreamError('诊断终态不一致，请按请求号回查。')
      terminal = { status, result }
    } else if (name === 'error') {
      const status =
        typeof parsed.status_code === 'number' ? parsed.status_code : undefined
      throw new DiagnosticStreamError(
        typeof parsed.message === 'string'
          ? parsed.message
          : '诊断流中断，请按请求号回查。',
        status,
        parsed.uncertain !== false
      )
    }
    update({ ...progress, tools: [...progress.tools] })
  }
  const consume = (chunk: string) => {
    pending += chunk
    for (;;) {
      const newline = pending.search(/[\r\n]/)
      if (
        newline < 0 ||
        (pending[newline] === '\r' && newline === pending.length - 1)
      )
        break
      const line = pending.slice(0, newline)
      const pair = pending.slice(newline, newline + 2) === '\r\n'
      pending = pending.slice(newline + (pair ? 2 : 1))
      if (!line) dispatch()
      else if (line.startsWith('event:')) eventName = line.slice(6).trimStart()
      else if (line.startsWith('data:')) {
        const data = line.slice(5).trimStart()
        eventSize += data.length
        if (eventSize > MAX_EVENT)
          throw new DiagnosticStreamError('诊断事件过大，请按请求号回查。')
        dataLines.push(data)
      }
      if (terminal) return
    }
    if (pending.length > MAX_EVENT)
      throw new DiagnosticStreamError('诊断事件过大，请按请求号回查。')
  }
  try {
    while (!terminal) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      const { value, done } = await reader.read()
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (done) {
        consume(decoder.decode())
        break
      }
      wireSize += value.byteLength
      if (wireSize > MAX_WIRE)
        throw new DiagnosticStreamError('诊断流过大，请按请求号回查。')
      const decoded = decoder.decode(value, { stream: true })
      for (let offset = 0; offset < decoded.length; offset += 16_000) {
        consume(decoded.slice(offset, offset + 16_000))
        if (terminal) break
      }
    }
    if (!terminal)
      throw new DiagnosticStreamError('诊断流未收到终态，请按请求号回查。')
    return terminal
  } finally {
    signal.removeEventListener('abort', cancelReader)
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
