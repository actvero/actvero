import type { Schema } from '@/lib/api'
import { providerAvatarPicker } from '@/features/model-channels/provider-avatars'
import { capabilities, reasoningValues, type ModelValues } from './model-form'

export type ReferenceModel = Schema['ReferenceModel']

export function modelIcon(model: { icon?: string; icon_key?: string }) {
  return (
    model.icon ||
    providerAvatarPicker.options.find((p) => p.id === model.icon_key)?.image
  )
}

export function importModel(
  current: ModelValues,
  source: ReferenceModel,
  overwrite: boolean
): ModelValues {
  const result = structuredClone(current)
  if (!result.name || overwrite) result.name = source.name
  if (!result.slug || overwrite) result.slug = source.model_id
  if ((!result.vendor || overwrite) && source.developer_name)
    result.vendor = source.developer_name
  if ((!result.context_window || overwrite) && source.context_window)
    result.context_window = String(source.context_window)
  if ((!result.max_output || overwrite) && source.max_output)
    result.max_output = String(source.max_output)
  for (const [key] of capabilities) {
    if (
      (result.capabilities[key] === 'unknown' || overwrite) &&
      source.capabilities[key] !== 'unknown'
    ) {
      result.capabilities[key] = source.capabilities[key] ?? 'unknown'
      if (key === 'reasoning')
        result.reasoning = reasoningValues(source.reasoning_options)
    }
  }
  if (
    result.capabilities.reasoning === 'supported' &&
    source.capabilities.reasoning === 'supported' &&
    !current.reasoning.toggle &&
    !current.reasoning.effort &&
    !current.reasoning.budget
  ) {
    result.reasoning = reasoningValues(source.reasoning_options)
  }
  const aliases: Record<string, string> = {
    google: 'gemini',
    'google-vertex': 'gemini',
    'amazon-bedrock': 'aws',
    alibaba: 'bailian',
    'alibaba-cn': 'bailian',
    moonshotai: 'moonshot',
    'moonshotai-cn': 'moonshot',
    zai: 'zhipu',
    zhipuai: 'zhipu',
    siliconflow: 'siliconcloud',
  }
  const key = aliases[source.provider] ?? source.provider
  if (
    ((!result.icon && !result.icon_key) || overwrite) &&
    providerAvatarPicker.options.some((p) => p.id === key)
  ) {
    result.icon_key = key
    result.icon = ''
  }
  result.reference = {
    provider: source.provider,
    model_id: source.model_id,
  }
  return result
}
