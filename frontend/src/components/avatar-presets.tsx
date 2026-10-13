import { useRef, useState } from 'react'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { RequestError } from '@/components/request-state'

export type AvatarPreset = {
  id: string
  name: string
  /** Bundled, same-origin raster asset; never a third-party URL. */
  image: string
  keywords?: string[]
}

export type AvatarPresetPicker = {
  title: string
  description: string
  options: AvatarPreset[]
}

export function AvatarPresets({
  picker,
  close,
  restore,
  save,
}: {
  picker: AvatarPresetPicker
  close: () => void
  restore: () => void
  save: (file: File) => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState(false)
  const saving = useRef(false)
  const [error, setError] = useState<unknown>(null)
  const options = picker.options.filter((option) =>
    [option.name, ...(option.keywords ?? [])]
      .join(' ')
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase())
  )

  async function choose(option: AvatarPreset) {
    if (saving.current) return
    saving.current = true
    setPending(true)
    setError(null)
    try {
      const url = new URL(option.image, window.location.href)
      if (url.origin !== window.location.origin)
        throw new Error('图标必须来自本地资源库')
      const response = await fetch(url.href, {
        credentials: 'omit',
        redirect: 'error',
        signal: AbortSignal.timeout(10000),
      })
      if (!response.ok) throw new Error('图标加载失败，请重试')
      const blob = await response.blob()
      if (
        !['image/png', 'image/jpeg', 'image/webp'].includes(blob.type) ||
        blob.size > 256 * 1024
      )
        throw new Error('图标无法读取，请重新选择')
      await save(new File([blob], option.id, { type: blob.type }))
    } catch (e) {
      setError(e)
    } finally {
      saving.current = false
      setPending(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !saving.current && close()}>
      <DialogContent
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg'
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restore()
        }}
      >
        <DialogHeader>
          <DialogTitle>{picker.title}</DialogTitle>
          <DialogDescription>{picker.description}</DialogDescription>
        </DialogHeader>
        <Input
          aria-label='搜索图标'
          placeholder='搜索名称…'
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          disabled={pending}
        />
        <ScrollArea className='h-72'>
          <div
            className='grid grid-cols-2 gap-2 p-1 sm:grid-cols-3'
            aria-busy={pending}
          >
            {options.map((option) => (
              <Button
                key={option.id}
                type='button'
                variant='outline'
                className='h-auto min-w-0 flex-col gap-2 px-2 py-3'
                disabled={pending}
                aria-label={option.name}
                onClick={() => void choose(option)}
              >
                <Avatar size='md'>
                  <AvatarImage src={option.image} alt='' />
                  <AvatarFallback>{option.name.slice(0, 1)}</AvatarFallback>
                </Avatar>
                <span className='max-w-full truncate'>{option.name}</span>
              </Button>
            ))}
          </div>
          {options.length === 0 && (
            <p
              role='status'
              className='py-8 text-center text-sm text-muted-foreground'
            >
              没有匹配的图标，可换个名称搜索或返回上传图片。
            </p>
          )}
        </ScrollArea>
        {!!error && <RequestError error={error} />}
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={pending}
            onClick={close}
          >
            取消
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
