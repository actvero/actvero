import type { Schema } from '@/lib/api'
import type { ProviderModule } from './provider-modules'
import type { Detail } from './shared'

type Source = Pick<Detail, 'base_url' | 'connection'>
const normalized = (value: string) => value.trim().replace(/\/+$/, '')

export function channelBaseUrl(provider?: ProviderModule, source?: Source) {
  const connection = source?.connection
  if (connection?.address_mode === 'legacy_api_base')
    return connection.legacy_base_url ?? source!.base_url
  const root = connection?.service_root ?? provider?.official_service_root
  if (!root) return source?.base_url ?? provider?.default_base_url ?? ''
  return (
    normalized(root) +
    (connection?.api_prefix ?? provider?.default_api_prefix ?? '')
  )
}

export function connectionForBaseUrl(
  value: string,
  provider: ProviderModule,
  source?: Source
): Schema['ChannelConnectionSettings'] {
  const base = normalized(value)
  // Keep saved resolver semantics, including legacy targets and explicit empty
  // prefixes, when editing metadata or copying an unchanged address.
  if (source && base === normalized(channelBaseUrl(provider, source)))
    return source.connection
  if (
    provider.official_service_root &&
    base === normalized(channelBaseUrl(provider))
  )
    return { address_mode: 'provider_default', resolver_version: 1 }
  try {
    const url = new URL(base)
    // The form exposes one full BaseURL. The existing API accepts the origin
    // and exact path separately; never append a second provider prefix.
    return {
      address_mode: 'service_root',
      service_root: url.origin,
      api_prefix: base.match(/^https?:\/\/[^/]+(\/.*)?$/i)?.[1] ?? '',
      resolver_version: 1,
    }
  } catch {
    // Invalid drafts remain editable; form validation prevents sending them.
    return {
      address_mode: 'service_root',
      service_root: base,
      api_prefix: '',
      resolver_version: 1,
    }
  }
}
