import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Camera, ImagePlus, Images, RotateCcw, Trash2 } from 'lucide-react'
import Cropper, { type Area } from 'react-easy-crop'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { RequestError } from '@/components/request-state'
import { AvatarPresets, type AvatarPresetPicker } from './avatar-presets'

// Shared by profiles and resource presentation. Uploads are cropped; bundled presets keep their artwork.
export function AvatarEditor({
  value,
  fallback,
  label = '头像',
  disabled,
  presetPicker,
  resetToDefault = false,
  onChange,
}: {
  value?: string | null
  fallback: ReactNode
  label?: string
  disabled?: boolean
  presetPicker?: AvatarPresetPicker
  resetToDefault?: boolean
  onChange: (file: File | null) => Promise<void> | void
}) {
  const input = useRef<HTMLInputElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [presetsOpen, setPresetsOpen] = useState(false)
  const [source, setSource] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(
    () => () => {
      if (source?.startsWith('blob:')) URL.revokeObjectURL(source)
    },
    [source]
  )
  const actionLabel = `编辑${label}`
  async function remove() {
    if (busy || disabled || !value) return
    setBusy(true)
    setError(null)
    try {
      await onChange(null)
      setMenuOpen(false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className='shrink-0'>
      <DropdownMenu
        open={menuOpen}
        onOpenChange={(open) => {
          if (busy) return
          if (open) setError(null)
          setMenuOpen(open)
        }}
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                ref={trigger}
                type='button'
                variant='ghost'
                className='relative size-16 rounded-full p-0'
                disabled={disabled || busy}
                aria-label={actionLabel}
              >
                <Avatar size='lg'>
                  <AvatarImage src={value || undefined} alt='' />
                  <AvatarFallback size='lg'>{fallback}</AvatarFallback>
                </Avatar>
                <span className='absolute right-0 bottom-0 flex size-5 items-center justify-center rounded-full border border-background bg-primary text-primary-foreground'>
                  <Camera className='size-3' />
                </span>
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>{actionLabel}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent
          align='start'
          className='max-w-xs'
          onCloseAutoFocus={(e) => {
            // Let the crop dialog keep focus when the selected file opens it.
            if (source || presetsOpen) e.preventDefault()
          }}
        >
          <DropdownMenuGroup>
            {presetPicker && (
              <DropdownMenuItem
                disabled={disabled || busy}
                onSelect={() => {
                  setMenuOpen(false)
                  setPresetsOpen(true)
                }}
              >
                <Images />
                {presetPicker.title}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              disabled={disabled || busy}
              onSelect={(e) => {
                e.preventDefault()
                input.current?.click()
              }}
            >
              <ImagePlus />
              {presetPicker ? '上传图片' : '更换'}
            </DropdownMenuItem>
            <DropdownMenuItem
              variant={resetToDefault ? 'default' : 'destructive'}
              disabled={disabled || busy || !value}
              onSelect={(e) => {
                e.preventDefault()
                void remove()
              }}
            >
              {resetToDefault ? <RotateCcw /> : <Trash2 />}
              {resetToDefault
                ? busy
                  ? '处理中…'
                  : '恢复默认'
                : busy
                  ? '移除中…'
                  : '移除'}
            </DropdownMenuItem>
          </DropdownMenuGroup>
          {!!error && (
            <>
              <DropdownMenuSeparator />
              <RequestError error={error} />
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <Input
        ref={input}
        className='hidden'
        type='file'
        accept='image/png,image/jpeg,image/webp'
        aria-label={`选择${label}`}
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          if (
            !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) ||
            file.size > 2 * 1024 * 1024
          ) {
            setMenuOpen(true)
            setError(new Error('请选择不超过 2 MB 的 PNG、JPG 或 WebP 图片'))
            return
          }
          setError(null)
          setMenuOpen(false)
          setSource(URL.createObjectURL(file))
        }}
      />
      {presetsOpen && presetPicker && (
        <AvatarPresets
          picker={presetPicker}
          close={() => setPresetsOpen(false)}
          restore={() => trigger.current?.focus()}
          save={async (file) => {
            await onChange(file)
            setPresetsOpen(false)
          }}
        />
      )}
      {source && (
        <CropDialog
          key={source}
          source={source}
          label={label}
          close={() => setSource(null)}
          restore={() => trigger.current?.focus()}
          save={async (file) => {
            await onChange(file)
            setSource(null)
          }}
        />
      )}
    </div>
  )
}

function CropDialog({
  source,
  label,
  close,
  restore,
  save,
}: {
  source: string
  label: string
  close: () => void
  restore: () => void
  save: (file: File) => Promise<void>
}) {
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [area, setArea] = useState<Area | null>(null)
  const [ready, setReady] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const zoomId = useId()
  async function apply() {
    if (!ready || !area || pending) return
    setPending(true)
    setError(null)
    try {
      const image = new Image()
      image.src = source
      await image.decode()
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = 256
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('当前浏览器无法处理图片')
      ctx.drawImage(
        image,
        area.x,
        area.y,
        area.width,
        area.height,
        0,
        0,
        256,
        256
      )
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error('裁剪失败，请重试'))),
          'image/webp',
          0.9
        )
      )
      if (blob.size > 256 * 1024) throw new Error('图片过大，请换一张图片')
      await save(new File([blob], 'avatar.webp', { type: blob.type }))
    } catch (e) {
      setError(e)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) close()
      }}
    >
      <DialogContent
        motion='fade'
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md'
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
      >
        <DialogHeader>
          <DialogTitle>调整{label}</DialogTitle>
          <DialogDescription>
            拖动图片调整位置，使用滑块缩放。也可聚焦图片后按方向键移动。
          </DialogDescription>
        </DialogHeader>
        <div
          className='relative aspect-square w-full overflow-hidden rounded-md bg-muted'
          aria-busy={pending}
        >
          <Cropper
            image={source}
            crop={crop}
            zoom={zoom}
            aspect={1}
            cropShape='round'
            showGrid={false}
            maxZoom={3}
            zoomWithScroll={false}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropAreaChange={(_, pixels) => setArea(pixels)}
            onMediaLoaded={(media) => {
              if (media.naturalWidth * media.naturalHeight > 16_000_000) {
                setReady(false)
                setError(
                  new Error('图片分辨率过大，请使用不超过 1600 万像素的图片')
                )
              } else setReady(true)
            }}
            mediaProps={{
              onError: () => {
                setReady(false)
                setError(new Error('图片无法读取，请重新选择'))
              },
            }}
            classes={{
              containerClassName:
                'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
            }}
            cropperProps={{
              'aria-label': '图片裁剪区域',
              'aria-disabled': pending,
              tabIndex: pending ? -1 : 0,
            }}
            style={{
              containerStyle: { pointerEvents: pending ? 'none' : undefined },
              cropAreaStyle: {
                borderColor: 'var(--border)',
                color: 'color-mix(in srgb, var(--background) 70%, transparent)',
              },
            }}
          />
        </div>
        <div className='flex flex-col gap-3'>
          <div className='flex justify-between'>
            <Label htmlFor={zoomId}>缩放</Label>
            <span className='text-sm text-muted-foreground'>
              {Math.round(zoom * 100)}%
            </span>
          </div>
          <Slider
            id={zoomId}
            thumbLabel='缩放'
            value={[zoom]}
            onValueChange={([v]) => setZoom(v)}
            min={1}
            max={3}
            step={0.05}
            disabled={pending || !ready}
          />
        </div>
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
          <Button
            type='button'
            disabled={pending || !ready || !area}
            onClick={() => void apply()}
          >
            {pending ? '处理中…' : '应用裁剪'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
