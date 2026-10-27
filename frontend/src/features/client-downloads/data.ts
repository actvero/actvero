import { queryOptions } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'

export type Release = Schema['ReleaseView']
export type Asset = Schema['ClientAsset']
export type PublicRelease = Schema['PublicRelease']
export type Recommendation = Schema['RecommendationView']
export type PublicDownloads = Schema['PublicDownloads']
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

export function recommendedDownload(
  catalog: PublicDownloads,
  platform: Asset['platform'],
  architecture: string
) {
  const head = catalog.recommendations.find(
    (item) => item.platform === platform && item.architecture === architecture
  )
  const release = catalog.items.find((item) => item.id === head?.release_id)
  const asset = release?.assets.find(
    (item) => item.platform === platform && item.architecture === architecture
  )
  return release && asset ? { release, asset } : undefined
}

export function commonRecommendedVersion(catalog: PublicDownloads) {
  const versions = new Set(
    catalog.recommendations.flatMap(({ platform, architecture }) => {
      const download = recommendedDownload(catalog, platform, architecture)
      return download ? [download.release.version] : []
    })
  )
  return versions.size === 1 ? [...versions][0] : undefined
}

export function currentPlatform(
  userAgent: string
): Asset['platform'] | undefined {
  if (/Android|iPhone|iPad|iPod|Mobile/i.test(userAgent)) return undefined
  if (/Macintosh|Mac OS X/i.test(userAgent)) return 'macos'
  if (/Windows/i.test(userAgent)) return 'windows'
  return undefined
}

export const downloadArchitectureLabel = (
  platform: Asset['platform'],
  architecture: Asset['architecture']
) =>
  platform === 'macos'
    ? { arm64: 'Apple 芯片', x64: 'Intel 芯片', universal: 'Universal' }[
        architecture
      ]
    : architectureNames[architecture]

export const packageFormat = (filename: string) =>
  filename.match(/\.([a-z0-9]{2,7})$/i)?.[1].toUpperCase() ?? '安装包'
