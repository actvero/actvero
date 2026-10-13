import { useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { resourceIconGlyphs } from '@/lib/resource-icon-glyphs'
import {
  selectedIcon,
  type IconSelection,
  type IconOption,
} from '@/lib/resource-icons'
import { cn } from '@/lib/utils'
import { useReturnFocus } from '@/hooks/use-return-focus'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { AvatarEditor } from '@/components/avatar-editor'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'

export function IconPicker({
  value,
  name,
  options,
  loading,
  error,
  retry,
  automaticImage,
  automaticWarning,
  close,
  onChange,
}: {
  value: IconSelection
  name: string
  options: IconOption[]
  loading: boolean
  error?: unknown
  retry: () => void
  automaticImage?: string
  automaticWarning?: string
  close: () => void
  onChange: (value: IconSelection) => void
}) {
  const restore = useReturnFocus()
  const [draft, setDraft] = useState(value)
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<string>(
    value.source === 'auto' ? 'library' : value.source
  )
  const selected = options.find((option) => option.key === draft.key)
  const label =
    draft.source === 'auto'
      ? '跟随技能包'
      : draft.source === 'upload'
        ? '上传图片'
        : selected?.label || '图标库'
  const visible = options.filter((item) =>
    `${item.label} ${item.key} ${item.category}`
      .toLowerCase()
      .includes(search.trim().toLowerCase())
  )
  const categories = [...new Set(visible.map((item) => item.category))]
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        className={cn(
          'flex max-h-[90dvh] flex-col overflow-y-auto sm:max-w-2xl',
          tab === 'library' && 'h-[min(48rem,90dvh)]'
        )}
        onCloseAutoFocus={restore}
      >
        <DialogHeader className='shrink-0'>
          <DialogTitle>选择技能图标</DialogTitle>
          <DialogDescription>选择后，保存技能时生效。</DialogDescription>
        </DialogHeader>
        <Tabs
          value={tab}
          onValueChange={setTab}
          className={cn('min-h-0 flex-1', tab === 'library' && 'min-h-56')}
        >
          <TabsList className='w-full shrink-0'>
            <TabsTrigger value='library'>图标库</TabsTrigger>
            <TabsTrigger value='upload'>上传图片</TabsTrigger>
            <TabsTrigger value='auto'>跟随技能包</TabsTrigger>
          </TabsList>
          <TabsContent
            value='library'
            className='flex min-h-0 flex-col gap-3 px-1 pt-3'
          >
            <Input
              className='shrink-0'
              aria-label='搜索图标'
              placeholder='搜索名称或用途…'
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {loading ? (
              <LoadingState />
            ) : error ? (
              <RequestError error={error} retry={retry} />
            ) : (
              <div
                className='flex min-h-24 flex-1 flex-col gap-5 overflow-y-auto px-1 py-2'
                aria-label='可选图标'
              >
                {categories.map((category) => (
                  <section
                    key={category}
                    aria-label={category}
                    className='flex flex-col gap-2'
                  >
                    <h3 className='text-sm font-medium text-muted-foreground'>
                      {category}
                    </h3>
                    <div className='flex flex-wrap gap-2'>
                      {visible
                        .filter((item) => item.category === category)
                        .map((option) => {
                          const Glyph = resourceIconGlyphs[option.key]
                          return (
                            <Tooltip key={option.key} delayDuration={300}>
                              <TooltipTrigger asChild>
                                <Button
                                  type='button'
                                  size='icon'
                                  variant={
                                    draft.source === 'library' &&
                                    draft.key === option.key
                                      ? 'secondary'
                                      : 'ghost'
                                  }
                                  aria-label={option.label}
                                  aria-pressed={
                                    draft.source === 'library' &&
                                    draft.key === option.key
                                  }
                                  onClick={() =>
                                    setDraft({
                                      source: 'library',
                                      key: option.key,
                                    })
                                  }
                                >
                                  {Glyph ? (
                                    <Glyph aria-hidden='true' />
                                  ) : (
                                    <ResourceIcon
                                      image={option.image}
                                      name={option.label}
                                      size='sm'
                                    />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>{option.label}</TooltipContent>
                            </Tooltip>
                          )
                        })}
                    </div>
                  </section>
                ))}
                {!visible.length && (
                  <p className='col-span-full py-10 text-center text-sm text-muted-foreground'>
                    没有匹配的图标，试试其他关键词。
                  </p>
                )}
              </div>
            )}
          </TabsContent>
          <TabsContent value='upload' className='space-y-5 py-6'>
            <div className='flex items-center gap-4'>
              <AvatarEditor
                label='上传图标'
                value={draft.source === 'upload' ? draft.image : null}
                fallback={<ImagePlus />}
                onChange={async (file) => {
                  if (!file) {
                    setDraft({ source: 'auto' })
                    return
                  }
                  const image = await new Promise<string>((resolve, reject) => {
                    const reader = new FileReader()
                    reader.onload = () => resolve(String(reader.result))
                    reader.onerror = () =>
                      reject(new Error('图片读取失败，请重新选择'))
                    reader.readAsDataURL(file)
                  })
                  setDraft({ source: 'upload', image })
                }}
              />
              <div className='space-y-2 text-sm'>
                <p>点击图标选择图片并裁剪</p>
                <p className='text-muted-foreground'>
                  PNG、JPG 或 WebP，不超过 2 MB。
                </p>
              </div>
            </div>
          </TabsContent>
          <TabsContent value='auto' className='space-y-5 py-6'>
            <div className='flex items-center gap-4'>
              <ResourceIcon image={automaticImage} name={name} size='lg' />
              <div className='space-y-2 text-sm'>
                <p>
                  {automaticImage ? '包内图标' : '暂无包内图标，显示名称首字母'}
                </p>
                <p className='text-muted-foreground'>
                  自动跟随生效版本；手动选择图标后，新版本不会覆盖。
                </p>
              </div>
            </div>
            {automaticWarning && (
              <p role='status' className='text-sm text-muted-foreground'>
                {automaticWarning}
              </p>
            )}
            <Button
              type='button'
              variant='outline'
              onClick={() => setDraft({ source: 'auto' })}
            >
              恢复自动
            </Button>
          </TabsContent>
        </Tabs>
        <div className='flex shrink-0 items-center gap-3 border-t pt-4 text-sm'>
          <ResourceIcon
            image={selectedIcon(draft, options, automaticImage)}
            name={name}
            size='sm'
          />
          <span className='min-w-0 truncate'>已选：{label}</span>
        </div>
        <DialogFooter className='shrink-0'>
          <Button type='button' variant='outline' onClick={close}>
            取消选择
          </Button>
          <Button
            type='button'
            disabled={draft.source === 'library' && !selected}
            onClick={() => {
              onChange(draft)
              close()
            }}
          >
            使用此图标
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
