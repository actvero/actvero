import { useEffect, useRef } from 'react'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'

export function GeneratedImagePreview({
  image,
}: {
  image: Schema['GeneratedImage']
}) {
  const preview = useRef<HTMLImageElement>(null)
  const download = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    const bytes = Uint8Array.from(atob(image.b64_json), (char) =>
      char.charCodeAt(0)
    )
    const objectUrl = URL.createObjectURL(
      new Blob([bytes], { type: image.media_type })
    )
    if (preview.current) preview.current.src = objectUrl
    if (download.current) download.current.href = objectUrl
    return () => URL.revokeObjectURL(objectUrl)
  }, [image])
  const extension = image.media_type.split('/')[1]
  return (
    <div className='flex min-w-0 flex-col items-start gap-3'>
      <img
        ref={preview}
        alt='生成的测试图片'
        className='max-h-96 max-w-full object-contain'
      />
      <div className='flex flex-wrap items-center gap-3'>
        <span className='text-sm text-muted-foreground'>
          {image.width} × {image.height} · {Math.ceil(image.bytes / 1024)} KB
        </span>
        <Button asChild variant='outline' size='sm'>
          <a ref={download} download={`actvero-image.${extension}`}>
            下载图片
          </a>
        </Button>
      </div>
    </div>
  )
}
