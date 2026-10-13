import type { Schema } from '@/lib/api'
import type { Detail } from './shared'
import type { TestOperation } from './test-operations'

export type DiagnosticValues = {
  id: string
  operation: TestOperation | ''
  texts: string
  query: string
  count: string
  voice: string
  size: string
  quality: string
}

export type DiagnosticRecord = Schema['ChannelTestRecord'] & {
  health_certification?: 'not_requested' | 'certified' | 'not_certified'
}
export type DiagnosticView = Schema['ChannelTestView'] & {
  health_certification?: 'not_requested' | 'certified' | 'not_certified'
}
export type DiagnosticLookup = {
  channel_id: string
  record: DiagnosticRecord
  media_available: false
}

export const endpointFor: Record<TestOperation, string> = {
  chat: 'chat_completions',
  embedding: 'embeddings',
  rerank: 'rerank',
  image_generation: 'images',
  speech: 'speech',
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)

export function initialDiagnosticSelection(
  channel: Detail,
  operations: TestOperation[],
  initialModelId?: string,
  initialOperation?: TestOperation
): { id: string; operation: TestOperation | '' } {
  const modelKnown = (id: string) =>
    channel.models.some((item) => item.id === id)
  if (initialModelId || initialOperation) {
    return {
      id: initialModelId && modelKnown(initialModelId) ? initialModelId : '',
      operation:
        initialOperation && operations.includes(initialOperation)
          ? initialOperation
          : '',
    }
  }
  if (channel.test_defaults) {
    const saved = channel.test_defaults
    if (
      channel.test_defaults_status?.valid &&
      modelKnown(saved.upstream_id) &&
      operations.includes(saved.operation)
    )
      return { id: saved.upstream_id, operation: saved.operation }
    return { id: '', operation: '' }
  }
  return channel.models.length === 1 && operations.length === 1
    ? { id: channel.models[0].id, operation: operations[0] }
    : { id: '', operation: '' }
}

export function diagnosticInput(
  values: DiagnosticValues
): Record<string, unknown> {
  const count = values.count ? Number(values.count) : undefined
  switch (values.operation) {
    case 'chat':
      return { prompt: values.texts, max_output_tokens: count }
    case 'embedding':
      return {
        input: lines(values.texts),
        ...(count ? { dimensions: count } : {}),
      }
    case 'rerank':
      return {
        query: values.query,
        documents: lines(values.texts),
        ...(count ? { top_n: count } : {}),
      }
    case 'image_generation':
      return {
        prompt: values.texts,
        ...(values.size ? { size: values.size } : {}),
        ...(values.quality ? { quality: values.quality } : {}),
      }
    case 'speech':
      return {
        input: values.texts,
        voice: values.voice,
        response_format: 'wav',
      }
    default:
      throw new Error('请先选择测试接口')
  }
}

export function diagnosticBody(
  channel: Detail,
  values: DiagnosticValues,
  requestId: string,
  binding?: Schema['ChannelBindingReference'] | null,
  stream = false
) {
  if (!values.operation) throw new Error('请先选择测试接口')
  if (stream && values.operation !== 'chat')
    throw new Error('仅对话诊断支持流式测试')
  return {
    version: channel.version,
    request_id: requestId,
    upstream_id: values.id,
    operation: values.operation,
    endpoint: endpointFor[values.operation],
    stream,
    input: diagnosticInput(values),
    certify_health: !!binding,
    ...(binding
      ? {
          model_id: binding.model_id,
          model_version: (
            binding as typeof binding & { model_version?: number | null }
          ).model_version,
          binding_id: binding.binding_id,
        }
      : {}),
  }
}
