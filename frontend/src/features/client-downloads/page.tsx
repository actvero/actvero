import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import appleIcon from '@/assets/platforms/apple.svg'
import windowsIcon from '@/assets/platforms/windows.svg'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { LoadingState, RequestError } from '@/components/request-state'
import { useBranding } from '@/features/branding/data'
import { PublicLayout } from '@/features/portal/public-layout'
import {
  commonRecommendedVersion,
  currentPlatform,
  downloadArchitectureLabel,
  downloadHref,
  platformNames,
  packageFormat,
  publicDownloadsOptions,
  recommendedDownload,
  type Asset,
  type PublicDownloads,
} from './data'
import { ReleaseBrowser } from './release-browser'

export function ClientDownloadsPage() {
  const brand = useBranding()
  const query = useQuery(publicDownloadsOptions)
  const current = currentPlatform(navigator.userAgent)
  const order: Asset['platform'][] =
    current === 'macos' ? ['macos', 'windows'] : ['windows', 'macos']
  const catalog = !query.isError ? query.data : undefined
  const version = catalog ? commonRecommendedVersion(catalog) : undefined
  return (
    <PublicLayout variant='download'>
      <div className='mx-auto flex w-full max-w-[960px] flex-col gap-8 px-6 py-12 sm:px-8'>
        <div className='flex flex-col items-center gap-2 text-center'>
          <h1 className='text-[2rem] leading-tight font-semibold tracking-tight'>
            下载 {brand.name}
          </h1>
          {version && (
            <p
              className='text-sm text-muted-foreground'
              data-testid='download-version'
            >
              v{version}
            </p>
          )}
        </div>
        {query.isPending && <LoadingState />}
        {query.isError && (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        )}
        {catalog &&
          (catalog.items.length ? (
            <>
              <div className='grid items-stretch gap-4 md:grid-cols-2'>
                {order.map((platform) => (
                  <PlatformDownload
                    key={platform}
                    platform={platform}
                    catalog={catalog}
                    current={platform === current}
                    commonVersion={version}
                  />
                ))}
              </div>
              <div className='flex items-center justify-center gap-4 sm:gap-6'>
                <ReleaseBrowser releases={catalog.items} mode='notes' />
                <Separator orientation='vertical' className='h-4' />
                <ReleaseBrowser releases={catalog.items} mode='history' />
              </div>
            </>
          ) : (
            <p
              role='status'
              className='py-16 text-center text-muted-foreground'
            >
              客户端安装包暂未发布。
            </p>
          ))}
      </div>
    </PublicLayout>
  )
}

function PlatformDownload({
  platform,
  catalog,
  current,
  commonVersion,
}: {
  platform: Asset['platform']
  catalog: PublicDownloads
  current: boolean
  commonVersion?: string
}) {
  const available = new Set(
    catalog.items.flatMap((release) =>
      release.assets
        .filter((asset) => asset.platform === platform)
        .map((asset) => asset.architecture)
    )
  )
  const order: Asset['architecture'][] =
    platform === 'macos'
      ? ['arm64', 'x64', 'universal']
      : ['x64', 'arm64', 'universal']
  const architectures = order.filter((architecture) =>
    available.has(architecture)
  )
  const icon = platform === 'macos' ? appleIcon : windowsIcon
  return (
    <Card
      role='region'
      aria-label={platformNames[platform]}
      tone={current ? 'muted' : 'default'}
      className='min-w-0'
    >
      <CardHeader layout='row' className='justify-between gap-3 px-6'>
        <div className='flex items-center gap-3'>
          <img
            src={icon}
            alt=''
            aria-hidden
            className='size-6 shrink-0 dark:invert'
          />
          <CardTitle>
            <h2 className='text-xl tracking-tight'>
              {platformNames[platform]}
            </h2>
          </CardTitle>
        </div>
        {current && <Badge variant='secondary'>当前设备</Badge>}
      </CardHeader>
      <CardContent>
        {architectures.length ? (
          <ul className='flex flex-col gap-2'>
            {architectures.map((architecture) => {
              const label = downloadArchitectureLabel(platform, architecture)
              const download = recommendedDownload(
                catalog,
                platform,
                architecture
              )
              return (
                <li
                  key={architecture}
                  className='flex min-h-12 items-center justify-between gap-4'
                >
                  <div className='flex min-w-0 flex-col gap-1'>
                    <span className='text-sm font-medium'>{label}</span>
                    {download && download.release.version !== commonVersion && (
                      <span className='text-xs text-muted-foreground'>
                        v{download.release.version}
                      </span>
                    )}
                  </div>
                  {download ? (
                    <Button
                      asChild
                      size='lg'
                      variant={current ? 'default' : 'outline'}
                      className='h-11'
                    >
                      <a
                        href={downloadHref(download.release.id, download.asset)}
                        aria-label={`下载 ${platformNames[platform]} ${label}`}
                      >
                        <Download data-icon='inline-start' />
                        下载 {packageFormat(download.asset.filename)}
                      </a>
                    </Button>
                  ) : (
                    <Button
                      disabled
                      size='lg'
                      variant='outline'
                      className='h-11'
                      aria-label={`${platformNames[platform]} ${label}未设置推荐版本`}
                    >
                      未推荐
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        ) : (
          <p className='py-6 text-sm text-muted-foreground'>暂未发布</p>
        )}
      </CardContent>
    </Card>
  )
}
