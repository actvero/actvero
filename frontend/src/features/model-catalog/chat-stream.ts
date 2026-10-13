import { ApiError, type Schema } from '@/lib/api'

export type ChatResult = {
  content: string
  reasoning: string
  tools: Record<number, { id: string; name: string; arguments: string }>
  usage: unknown
}
type ChatEvent = {
  error?: { message?: string }
  usage?: unknown
  choices?: {
    message?: {
      content?: string
      reasoning_content?: string
      tool_calls?: ToolChunk[]
    }
    delta?: {
      content?: string
      reasoning_content?: string
      tool_calls?: ToolChunk[]
    }
  }[]
}
type ToolChunk = {
  index?: number
  id?: string
  function?: { name?: string; arguments?: string }
}

// Test response stays in component memory; never enters query caches or local storage.
export async function runChatTest(
  path: string,
  body: Schema['ChatInput'],
  csrf: string,
  signal: AbortSignal,
  update: (value: ChatResult) => void
): Promise<void> {
  const response = await fetch('/api/v1' + path, {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(response.status, error?.error?.message ?? '请求失败')
  }
  const result: ChatResult = {
    content: '',
    reasoning: '',
    tools: {},
    usage: null,
  }
  const apply = (event: ChatEvent) => {
    if (event.error) throw new Error(event.error.message ?? '流已中断')
    const delta = event.choices?.[0]?.delta ?? event.choices?.[0]?.message
    result.content += delta?.content ?? ''
    result.reasoning += delta?.reasoning_content ?? ''
    delta?.tool_calls?.forEach((c, position) => {
      const index = c.index ?? position
      const tool = result.tools[index] ?? { id: '', name: '', arguments: '' }
      result.tools[index] = {
        id: c.id ?? tool.id,
        name: tool.name + (c.function?.name ?? ''),
        arguments: tool.arguments + (c.function?.arguments ?? ''),
      }
    })
    if (event.usage != null) result.usage = event.usage
    update({ ...result, tools: { ...result.tools } })
  }
  if (!body.stream) {
    apply(await response.json())
    return
  }
  if (
    !response.body ||
    !response.headers.get('content-type')?.includes('text/event-stream')
  )
    throw new Error('未返回事件流')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let size = 0
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) throw new Error('事件流未完整结束，请查看调用记录')
      size += value.byteLength
      if (size > 16_000_000) throw new Error('测试响应过大')
      pending += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = pending.indexOf('\n\n')) >= 0) {
        const event = pending
          .slice(0, boundary)
          .split('\n')
          .filter((l) => l.startsWith('data:'))
          .map((l) => l.slice(5).trimStart())
          .join('\n')
        pending = pending.slice(boundary + 2)
        if (event === '[DONE]') return
        if (event) apply(JSON.parse(event))
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
