import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import appleIcon from '@/assets/platforms/apple.svg'
import windowsIcon from '@/assets/platforms/windows.svg'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
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
  publicDownloadsOptions,
  recommendedDownload,
  type Asset,
  type PublicDownloads,
} from './data'
import { AssetSummary, ReleaseBrowser } from './release-browser'

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
      <div className='mx-auto flex w-full max-w-[1280px] flex-col gap-14 px-6 py-14 sm:px-8 sm:pt-26 sm:pb-20'>
        <div className='flex flex-col items-center gap-3 text-center'>
          <h1 className='text-4xl font-semibold tracking-tight sm:text-6xl'>
            下载 {brand.name}
          </h1>
          {version && (
            <p
              className='text-lg text-muted-foreground'
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
              <div className='grid items-stretch gap-6 md:grid-cols-2'>
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
                <Separator orientation='vertical' className='h-6' />
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
  // A browser's OS does not reliably identify the CPU. Keep multiple choices explicit.
  const [choice, setChoice] = useState(() =>
    architectures.length === 1 ? architectures[0] : ''
  )
  const selected =
    architectures.find((architecture) => architecture === choice) ?? ''
  const download = recommendedDownload(catalog, platform, selected)
  const icon = platform === 'macos' ? appleIcon : windowsIcon
  return (
    <Card
      role='region'
      aria-label={platformNames[platform]}
      tone={current ? 'muted' : 'default'}
      className='min-w-0 gap-8 rounded-2xl py-8 sm:gap-10 sm:py-10'
    >
      <CardHeader layout='row' className='justify-between gap-3 px-6 sm:px-8'>
        <div className='flex items-center gap-4 sm:gap-6'>
          <img
            src={icon}
            alt=''
            aria-hidden
            className='size-10 shrink-0 sm:size-12 dark:invert'
          />
          <CardTitle>
            <h2 className='text-xl tracking-tight sm:text-3xl'>
              {platformNames[platform]}
            </h2>
          </CardTitle>
        </div>
        {current && (
          <Badge variant='secondary' className='rounded-full px-3 py-1'>
            当前设备
          </Badge>
        )}
      </CardHeader>
      <CardContent className='flex flex-col gap-4 px-6 sm:px-8'>
        {architectures.length ? (
          <>
            <RadioGroup
              variant='segmented-solid'
              value={selected}
              onValueChange={setChoice}
              aria-label={platformNames[platform] + ' 架构'}
              className='w-full flex-nowrap'
            >
              {architectures.map((architecture) => (
                <RadioGroupItem
                  key={architecture}
                  value={architecture}
                  variant='segmented-solid'
                  className='h-12 min-w-0 flex-1 px-2'
                >
                  {downloadArchitectureLabel(platform, architecture)}
                </RadioGroupItem>
              ))}
            </RadioGroup>
            <div aria-live='polite' className='min-h-5'>
              {download ? (
                <AssetSummary
                  asset={download.asset}
                  version={
                    download.release.version === commonVersion
                      ? undefined
                      : download.release.version
                  }
                />
              ) : (
                <p className='text-sm text-muted-foreground'>
                  {selected ? '未设置推荐版本' : '请选择架构'}
                </p>
              )}
            </div>
          </>
        ) : (
          <p className='py-6 text-sm text-muted-foreground'>暂未发布</p>
        )}
      </CardContent>
      <CardFooter className='mt-auto px-6 sm:px-8'>
        {download ? (
          <Button
            asChild
            size='download'
            variant={current ? 'default' : 'download-outline'}
            className='w-full'
          >
            <a href={downloadHref(download.release.id, download.asset)}>
              <Download data-icon='inline-start' />
              下载 {platformNames[platform]} 版
            </a>
          </Button>
        ) : (
          <Button disabled size='download' variant='outline' className='w-full'>
            <Download data-icon='inline-start' />
            下载 {platformNames[platform]} 版
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}
