import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Monitor, Apple, ChevronDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CopyableField } from '@/components/copyable-field'
import { LoadingState, RequestError } from '@/components/request-state'
import { useBranding } from '@/features/branding/data'
import { PublicLayout } from '@/features/portal/public-layout'
import {
  architectureLabel,
  downloadHref,
  platformNames,
  publicDownloadsOptions,
  sizeLabel,
  targetName,
  type Asset,
  type PublicRelease,
  type Recommendation,
} from './data'

export function ClientDownloadsPage() {
  const brand = useBranding()
  const query = useQuery(publicDownloadsOptions)
  const order: Asset['platform'][] = /Mac/i.test(navigator.userAgent)
    ? ['macos', 'windows']
    : ['windows', 'macos']
  return (
    <PublicLayout>
      <div className='mx-auto flex max-w-6xl flex-col gap-10 px-6 py-16 lg:px-8'>
        <div className='flex flex-col items-center gap-4 text-center'>
          <Badge variant='outline'>Windows · macOS</Badge>
          <h1 className='text-3xl font-semibold tracking-tight sm:text-5xl'>
            下载 {brand.name} 桌面端
          </h1>
          <p className='max-w-xl text-muted-foreground'>
            在桌面上使用团队授权的模型、工具与专家。
          </p>
        </div>
        {query.isPending && <LoadingState />}
        {query.isError && (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        )}
        {!query.isError && query.data && (
          <>
            {!query.data.items.length && (
              <p className='text-center text-muted-foreground'>
                客户端安装包暂未发布。
              </p>
            )}
            <div className='grid gap-6 md:grid-cols-2'>
              {order.map((platform) => (
                <PlatformDownload
                  key={platform}
                  platform={platform}
                  releases={query.data.items}
                  recommendations={query.data.recommendations}
                />
              ))}
            </div>
            {!!query.data.items.length && (
              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button variant='outline'>
                    已发布版本与更新说明
                    <ChevronDown />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className='mt-6 flex flex-col gap-4'>
                  {query.data.items.map((release) => (
                    <Card key={release.id}>
                      <CardHeader>
                        <CardTitle>v{release.version}</CardTitle>
                        <CardDescription>
                          {release.release_date}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className='flex flex-col gap-5'>
                        <p className='text-sm break-words whitespace-pre-wrap'>
                          {release.notes || '暂无更新说明。'}
                        </p>
                        {release.assets.map((asset) => (
                          <div
                            key={targetName(asset)}
                            className='flex min-w-0 flex-col gap-2'
                          >
                            <p className='text-sm text-muted-foreground'>
                              {targetName(asset)} · {asset.minimum_os} ·{' '}
                              {sizeLabel(asset.size_bytes)}
                            </p>
                            <Button asChild variant='outline' className='w-fit'>
                              <a href={downloadHref(release.id, asset)}>
                                下载 {targetName(asset)}
                              </a>
                            </Button>
                            {asset.sha256 && (
                              <CopyableField
                                label={'SHA256 · ' + targetName(asset)}
                                value={asset.sha256}
                                copyLabel='复制校验值'
                              />
                            )}
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            )}
            <Card>
              <CardHeader>
                <CardTitle>安装与登录</CardTitle>
              </CardHeader>
              <CardContent className='flex flex-col gap-3 text-sm text-muted-foreground'>
                <p>Windows：下载与你的系统架构对应的安装包，打开安装程序。</p>
                <p>
                  macOS：在「关于本机」确认 Apple Silicon 或 Intel；Universal
                  包适用于两种架构。DMG 打开后按提示安装。
                </p>
                <p>
                  安装后填写平台地址并登录，选择所属组织。可使用的模型、工具和专家由组织授权决定。
                </p>
                <p>安装包及校验值由平台发布方提供。系统要求以所选包为准。</p>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </PublicLayout>
  )
}

function PlatformDownload({
  platform,
  releases,
  recommendations,
}: {
  platform: Asset['platform']
  releases: PublicRelease[]
  recommendations: Recommendation[]
}) {
  const [choice, setChoice] = useState('')
  const architectures = [
    ...new Set(
      releases.flatMap((r) =>
        r.assets
          .filter((a) => a.platform === platform)
          .map((a) => a.architecture)
      )
    ),
  ]
  const selected = architectures.includes(choice as Asset['architecture'])
    ? choice
    : architectures.length === 1
      ? architectures[0]
      : ''
  const recommended = recommendations.find(
    (r) => r.platform === platform && r.architecture === selected
  )
  const release = releases.find((r) => r.id === recommended?.release_id)
  const asset = release?.assets.find(
    (a) => a.platform === platform && a.architecture === selected
  )
  const Icon = platform === 'windows' ? Monitor : Apple
  return (
    <Card className='min-w-0'>
      <CardHeader>
        <Icon className='mb-3 size-8' aria-hidden />
        <CardTitle>{platformNames[platform]}</CardTitle>
        <CardDescription>
          {asset && release
            ? 'v' + release.version + ' · ' + release.release_date
            : '选择适合你的安装包'}
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        {!architectures.length ? (
          <p className='text-sm text-muted-foreground'>
            该系统安装包暂未发布。
          </p>
        ) : (
          <>
            <Select value={selected} onValueChange={setChoice}>
              <SelectTrigger aria-label={platformNames[platform] + ' 架构'}>
                <SelectValue placeholder='请选择系统架构' />
              </SelectTrigger>
              <SelectContent>
                {architectures.map((arch) => (
                  <SelectItem key={arch} value={arch}>
                    {architectureLabel(platform, arch)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {asset && release ? (
              <>
                <p className='text-sm text-muted-foreground'>
                  {asset.minimum_os} · {sizeLabel(asset.size_bytes)}
                </p>
                <Button asChild size='lg'>
                  <a href={downloadHref(release.id, asset)}>
                    <Download />
                    下载 {platformNames[platform]} 版
                  </a>
                </Button>
                <p className='text-xs break-all text-muted-foreground'>
                  {asset.filename}
                </p>
                <Collapsible>
                  <CollapsibleTrigger asChild>
                    <Button variant='ghost' size='sm'>
                      更新说明与文件校验
                      <ChevronDown />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className='mt-3 flex min-w-0 flex-col gap-3'>
                    <p className='text-sm break-words whitespace-pre-wrap'>
                      {release.notes || '暂无更新说明。'}
                    </p>
                    {asset.sha256 ? (
                      <CopyableField
                        label='SHA256'
                        value={asset.sha256}
                        copyLabel='复制校验值'
                      />
                    ) : (
                      <p className='text-sm text-muted-foreground'>
                        发布方未提供校验值。
                      </p>
                    )}
                  </CollapsibleContent>
                </Collapsible>
              </>
            ) : (
              <>
                <Button disabled size='lg'>
                  下载 {platformNames[platform]} 版
                </Button>
                <p className='text-sm text-muted-foreground'>
                  {selected
                    ? '该架构暂未设置推荐安装包，可在已发布版本中查看。'
                    : '请选择架构后下载。'}
                </p>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
