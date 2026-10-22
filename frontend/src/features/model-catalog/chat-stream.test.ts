import { afterEach, expect, it, vi } from 'vitest'
import { runChatTest } from './chat-stream'

afterEach(() => vi.unstubAllGlobals())

it('reports the specific interruption and preserves content already delivered', async () => {
  const message = '模型连续 180 秒未返回新的输出'
  const frames = [
    {
      choices: [
        { delta: { content: '已生成的内容', reasoning_content: '思考过程' } },
      ],
    },
    { error: { code: 'upstream_idle_timeout', message } },
  ]
    .map((event) => `data: ${JSON.stringify(event)}\n\n`)
    .join('')
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(frames, {
          headers: { 'content-type': 'text/event-stream' },
        })
    )
  )
  const update = vi.fn()
  await expect(
    runChatTest(
      '/test/chat',
      {
        model: 'test',
        n: 1,
        messages: [{ role: 'user', content: 'test' }],
        stream: true,
      },
      'csrf',
      new AbortController().signal,
      update
    )
  ).rejects.toThrow(message)
  expect(update).toHaveBeenLastCalledWith(
    expect.objectContaining({
      content: '已生成的内容',
      reasoning: '思考过程',
    })
  )
})
