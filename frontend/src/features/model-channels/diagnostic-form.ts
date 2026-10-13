import { z } from 'zod'
import { imageFields } from './image-test-schema'
import type { TestOperation } from './test-operations'

const lines = (text: string) =>
  text
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
export const sampleFor = (operation: TestOperation | '') => ({
  texts:
    operation === 'speech'
      ? '你好，欢迎使用 Actvero。'
      : operation === 'image_generation'
        ? '一只坐在窗边的橘猫，水彩画风。'
        : operation === 'embedding'
          ? '这是一条测试文本。'
          : operation === 'rerank'
            ? '北京是中国的首都。\n上海位于中国东部。'
            : '请回复：连接成功',
  query: operation === 'rerank' ? '中国的首都在哪里？' : '',
  count: operation === 'chat' ? '64' : '',
})
export const diagnosticFormSchema = z
  .object({
    id: z.string().min(1, '请选择模型'),
    operation: z.enum([
      '',
      'chat',
      'embedding',
      'rerank',
      'image_generation',
      'speech',
    ]),
    texts: z.string().trim().min(1, '请输入测试内容'),
    query: z.string().trim().max(2000),
    count: z.string(),
    voice: z.string().trim(),
    ...imageFields,
  })
  .superRefine((values, ctx) => {
    const problem = (
      path: 'operation' | 'texts' | 'query' | 'count' | 'voice',
      message: string
    ) => ctx.addIssue({ code: 'custom', path: [path], message })
    if (!values.operation) problem('operation', '请选择测试接口')
    const items = ['chat', 'image_generation', 'speech'].includes(
      values.operation
    )
      ? [values.texts]
      : lines(values.texts)
    if (
      !items.length ||
      items.length > 8 ||
      items.some((item) => item.length > 2000)
    )
      problem('texts', '最多 8 条，每条最多 2000 字符')
    if (values.operation === 'speech') {
      if (Array.from(values.texts).length > 1000)
        problem('texts', '最多 1000 字符')
      if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}$/.test(values.voice))
        problem('voice', '请填写有效的上游音色 ID')
    }
    if (values.operation === 'rerank' && !values.query)
      problem('query', '请输入查询内容')
    if (
      !['image_generation', 'speech'].includes(values.operation) &&
      (values.count || values.operation === 'chat')
    ) {
      const count = Number(values.count)
      const max =
        values.operation === 'chat'
          ? 512
          : values.operation === 'embedding'
            ? 65536
            : items.length
      if (!Number.isInteger(count) || count < 1 || count > max)
        problem('count', `请输入 1 至 ${max} 的整数`)
    }
  })
