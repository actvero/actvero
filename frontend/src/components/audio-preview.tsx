import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

// Native controls retain browser decoding, keyboard interaction and accessibility.
export function AudioPreview({
  audio,
}: {
  audio: {
    b64_json: string
    media_type: 'audio/wav'
    duration_ms: number
    bytes: number
  }
}) {
  const player = useRef<HTMLAudioElement>(null)
  const download = useRef<HTMLAnchorElement>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const bytes = Uint8Array.from(atob(audio.b64_json), (char) =>
      char.charCodeAt(0)
    )
    const url = URL.createObjectURL(
      new Blob([bytes], { type: audio.media_type })
    )
    const element = player.current
    if (element) element.src = url
    if (download.current) download.current.href = url
    return () => {
      if (element) {
        element.pause()
        element.removeAttribute('src')
        element.load()
      }
      URL.revokeObjectURL(url)
    }
  }, [audio])
  return (
    <div className='flex min-w-0 flex-col gap-3'>
      <audio
        ref={player}
        aria-label='生成的语音'
        controls
        preload='metadata'
        className='w-full'
        onError={() => {
          if (player.current?.getAttribute('src')) setFailed(true)
        }}
        onLoadedMetadata={() => setFailed(false)}
      />
      {failed && <p role='alert'>浏览器无法播放，可下载音频。</p>}
      <div className='flex flex-wrap items-center gap-3'>
        <span className='text-sm text-muted-foreground'>
          AI 合成语音 · WAV · {(audio.duration_ms / 1000).toFixed(2)} 秒 ·{' '}
          {Math.ceil(audio.bytes / 1024)} KB
        </span>
        <Button asChild variant='outline' size='sm'>
          <a ref={download} download='actvero-speech.wav'>
            下载音频
          </a>
        </Button>
      </div>
    </div>
  )
}
