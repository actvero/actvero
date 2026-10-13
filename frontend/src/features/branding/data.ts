import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export const brandSlots = [
  'mark_light',
  'mark_dark',
  'wordmark_light',
  'wordmark_dark',
  'favicon',
] as const
export type BrandSlot = (typeof brandSlots)[number]
export type Branding = {
  name: string
  revision: string
  assets: Partial<Record<BrandSlot, string>>
  asset_ids: Partial<Record<BrandSlot, string>>
  favicon_url: string
  apple_icon_url: string
}
export type BrandingSettings = Branding & {
  identity_status: 'applied' | 'pending'
}
export const defaultBrand: Branding = {
  name: 'Actvero',
  revision: '00000000-0000-0000-0000-000000000000',
  assets: {},
  asset_ids: {},
  favicon_url: '/favicon.ico',
  apple_icon_url: '/brand/actvero-icon.png',
}
function initialBrand(): Branding | undefined {
  try {
    const text = document.getElementById('platform-branding')?.textContent
    if (!text) return undefined
    const value = JSON.parse(text) as Branding
    return value.name && value.revision && value.assets ? value : undefined
  } catch {
    return undefined
  }
}
export const brandOptions = queryOptions({
  queryKey: ['public', 'branding'],
  queryFn: async () => {
    const value = await api<Branding>('/platform/branding')
    if (!value.name || !value.revision || !value.assets || !value.asset_ids)
      throw new Error('品牌资料暂不可用')
    return value
  },
  initialData: initialBrand,
  staleTime: 15_000,
  refetchInterval: 30_000,
})
export function useBranding() {
  return useQuery(brandOptions).data ?? defaultBrand
}
