import type { ModelValues } from './model-form'

export function activationDraft(value: ModelValues): ModelValues {
  const next = structuredClone(value)
  next.access.enabled = true
  next.operation_enabled = true
  if (next.routing.mode === 'fixed') {
    if (!next.access.channel_id && next.bindings.length === 1) {
      next.access.channel_id = next.bindings[0].channel_id
      next.access.upstream_id = next.bindings[0].upstream_id
    }
    for (const binding of next.bindings) {
      if (
        binding.channel_id === next.access.channel_id &&
        binding.upstream_id === next.access.upstream_id
      )
        binding.enabled = true
    }
  }
  return next
}

export function issueTab(path: PropertyKey[]) {
  if (path[0] === 'budget_price' || path.includes('price')) return 'prices'
  if (
    path[0] === 'bindings' ||
    path[0] === 'routing' ||
    path.includes('channel_id') ||
    path.includes('upstream_id')
  )
    return 'bindings'
  if (path[0] === 'access') return 'access'
  return 'profile'
}
