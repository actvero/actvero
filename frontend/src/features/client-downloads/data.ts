import { queryOptions } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'

export type Release = Schema['ReleaseView']
export type Asset = Schema['ClientAsset']
export type PublicRelease = Schema['PublicRelease']
export type Recommendation = Schema['RecommendationView']
export const platformNames = { windows: 'Windows', macos: 'macOS' } as const
export const architectureNames = {
  x64: 'x64',
  arm64: 'ARM64',
  universal: 'Universal',
} as const
export const publicDownloadsOptions = queryOptions({
  queryKey: ['public', 'client-downloads'],
  queryFn: ({ signal }) =>
    api<Schema['PublicDownloads']>(
      '/platform/downloads/public',
      'GET',
      undefined,
      undefined,
      signal
    ),
  staleTime: 0,
  retry: false,
})
export const downloadHref = (id: string, asset: Asset) =>
  '/api/v1/platform/downloads/' +
  encodeURIComponent(id) +
  '/file?platform=' +
  asset.platform +
  '&architecture=' +
  asset.architecture
export const architectureLabel = (
  platform: Asset['platform'],
  architecture: Asset['architecture']
) =>
  platform === 'macos'
    ? {
        x64: 'Intel (x64)',
        arm64: 'Apple Silicon (ARM64)',
        universal: 'Universal',
      }[architecture]
    : architectureNames[architecture]
export const targetName = (asset: Pick<Asset, 'platform' | 'architecture'>) =>
  platformNames[asset.platform] +
  ' · ' +
  architectureLabel(asset.platform, asset.architecture)
export const sizeLabel = (bytes: number | null | undefined) =>
  bytes == null
    ? '大小未提供'
    : (bytes / 1024 / 1024).toLocaleString('zh-CN', {
        maximumFractionDigits: 1,
      }) + ' MB'
