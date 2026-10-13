import type { z } from 'zod'
import { diagnosticFormSchema } from './diagnostic-form'
import type { TestOperation } from './test-operations'

export type BatchValues = z.infer<typeof diagnosticFormSchema>

export function emptyBatchValues(
  id: string,
  operation: TestOperation
): BatchValues {
  return {
    id,
    operation,
    texts: '',
    query: '',
    count: '',
    voice: '',
    size: '',
    quality: '',
  }
}

export function validBatchValues(values: BatchValues) {
  return diagnosticFormSchema.safeParse(values).success
}

export function batchInputSummary(values: BatchValues) {
  const count = values.texts.split('\n').filter((item) => item.trim()).length
  if (values.operation === 'chat')
    return `提示词 ${values.texts.length} 字 · 输出上限 ${values.count || '未填写'}`
  if (values.operation === 'embedding')
    return `文本 ${count} 条 · 维度 ${values.count || '上游默认'}`
  return `查询 ${values.query.length} 字 · 文档 ${count} 条 · 返回数量 ${values.count || '全部'}`
}
