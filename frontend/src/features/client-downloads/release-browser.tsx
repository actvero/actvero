import { ChevronRight, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { CopyableField } from '@/components/copyable-field'
import {
  downloadHref,
  packageFormat,
  sizeLabel,
  targetName,
  type Asset,
  type PublicRelease,
} from './data'

export function AssetSummary({
  asset,
  version,
}: {
  asset: Asset
  version?: string
}) {
  return (
    <p className='text-sm break-words text-muted-foreground'>
      {[
        packageFormat(asset.filename),
        version && 'v' + version,
        asset.minimum_os,
        asset.size_bytes != null && sizeLabel(asset.size_bytes),
      ]
        .filter(Boolean)
        .join(' · ')}
    </p>
  )
}

export function ReleaseBrowser({
  releases,
  mode,
}: {
  releases: PublicRelease[]
  mode: 'notes' | 'history'
}) {
  const title = mode === 'notes' ? '更新日志' : '历史版本'
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant='ghost'>
          {title}
          <ChevronRight data-icon='inline-end' />
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[85svh] overflow-y-auto sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className='sr-only'>
            已发布客户端的{title}。
          </DialogDescription>
        </DialogHeader>
        <div className='flex min-w-0 flex-col divide-y'>
          {releases.map((release) => (
            <section
              key={release.id}
              className='flex min-w-0 flex-col gap-5 py-6 first:pt-2'
            >
              <div className='flex flex-wrap items-baseline justify-between gap-2'>
                <h3 className='font-semibold'>v{release.version}</h3>
                <time
                  dateTime={release.release_date}
                  className='text-sm text-muted-foreground'
                >
                  {release.release_date}
                </time>
              </div>
              <p className='text-sm break-words whitespace-pre-wrap'>
                {release.notes || '暂无更新说明。'}
              </p>
              {mode === 'history' &&
                release.assets.map((asset) => (
                  <div
                    key={targetName(asset)}
                    className='flex min-w-0 flex-col gap-3 rounded-lg border p-4'
                  >
                    <div className='flex flex-wrap items-center justify-between gap-3'>
                      <p className='text-sm font-medium'>{targetName(asset)}</p>
                      <Button asChild variant='outline' size='sm'>
                        <a href={downloadHref(release.id, asset)}>
                          <Download data-icon='inline-start' />
                          下载 {targetName(asset)}
                        </a>
                      </Button>
                    </div>
                    <AssetSummary asset={asset} />
                    <Collapsible>
                      <CollapsibleTrigger asChild>
                        <Button variant='ghost' size='sm'>
                          文件信息与校验
                          <ChevronRight data-icon='inline-end' />
                        </Button>
                      </CollapsibleTrigger>
                      <CollapsibleContent className='flex min-w-0 flex-col gap-3 pt-3'>
                        <p className='text-xs break-all text-muted-foreground'>
                          {asset.filename}
                        </p>
                        {asset.sha256 ? (
                          <CopyableField
                            label={'SHA256 · ' + targetName(asset)}
                            value={asset.sha256}
                            copyLabel='复制校验值'
                          />
                        ) : (
                          <p className='text-sm text-muted-foreground'>
                            未提供校验值
                          </p>
                        )}
                      </CollapsibleContent>
                    </Collapsible>
                  </div>
                ))}
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
