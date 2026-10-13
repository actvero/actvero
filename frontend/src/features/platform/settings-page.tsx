import { useState } from 'react'
import { z } from 'zod'
import { useForm, useFormState, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { BrandLockup, BrandMark } from '@/features/branding/brand'
import {
  brandSlots,
  type BrandSlot,
  type Branding,
  type BrandingSettings,
} from '@/features/branding/data'

type DraftAsset = {
  content: string
  url: string
  width: number
  height: number
}
type DraftAssets = Partial<Record<BrandSlot, DraftAsset | null>>
const schema = z.object({
  platform_name: z
    .string()
    .trim()
    .min(1, '请输入平台名称')
    .max(80, '最多 80 个字符'),
})
const slots: { slot: BrandSlot; title: string; hint: string }[] = [
  {
    slot: 'mark_light',
    title: '方形图标 · 浅色背景',
    hint: '推荐透明 PNG，512 × 512，用于侧栏和紧凑入口。',
  },
  {
    slot: 'mark_dark',
    title: '方形图标 · 深色背景（可选）',
    hint: '搭配浅色版使用。未上传时沿用浅色版，并使用浅色底板。',
  },
  {
    slot: 'wordmark_light',
    title: '横版 Logo · 浅色背景（可选）',
    hint: '推荐透明 PNG，如 1200 × 300，包含品牌文字。用于登录、门户和邮件。',
  },
  {
    slot: 'wordmark_dark',
    title: '横版 Logo · 深色背景（可选）',
    hint: '搭配浅色版使用，保持原始比例。未上传时沿用浅色版。',
  },
  {
    slot: 'favicon',
    title: '浏览器小图标（可选）',
    hint: '推荐简化图形，256 × 256。未上传时从方形图标生成。',
  },
]

export function PlatformGeneralSettingsPage() {
  const query = useQuery({
    queryKey: ['platform', 'branding-settings'],
    queryFn: () => api<BrandingSettings>('/platform/branding/settings'),
    refetchInterval: (q) =>
      q.state.data?.identity_status === 'pending' ? 5000 : false,
  })
  return (
    <PageShell title='品牌形象'>
      {query.isPending && <LoadingState />}
      {query.isError && (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data && <BrandSettings saved={query.data} />}
    </PageShell>
  )
}

function BrandSettings({ saved: latest }: { saved: BrandingSettings }) {
  const [saved, setSaved] = useState(latest)
  const { data: session } = useSession()
  const client = useQueryClient()
  const [assets, setAssets] = useState<DraftAssets>({})
  const [uploadError, setUploadError] = useState<unknown>(null)
  const [reading, setReading] = useState(false)
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    mode: 'onChange',
    defaultValues: { platform_name: saved.name },
  })
  const name = useWatch({ control: form.control, name: 'platform_name' })
  const { isDirty, isValid } = useFormState({ control: form.control })
  const dirty = isDirty || Object.keys(assets).length > 0
  const preview: Branding = {
    ...saved,
    name: name || saved.name,
    assets: { ...saved.assets },
  }
  for (const slot of brandSlots) {
    if (assets[slot] === null) delete preview.assets[slot]
    else if (assets[slot]) preview.assets[slot] = assets[slot].url
  }
  const smallIcon =
    preview.assets.favicon || preview.assets.mark_light || saved.favicon_url
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      api<BrandingSettings>(
        '/platform/branding/settings',
        'PUT',
        {
          ...values,
          revision: saved.revision,
          assets: Object.fromEntries(
            brandSlots.map((slot) => [
              slot,
              assets[slot] === null
                ? null
                : assets[slot]
                  ? { content: assets[slot].content }
                  : (saved.asset_ids[slot] ?? null),
            ])
          ),
        },
        session?.csrf
      ),
    onSuccess: async (value) => {
      client.setQueryData(['platform', 'branding-settings'], value)
      client.setQueryData(['public', 'branding'], value)
      setSaved(value)
      form.reset({ platform_name: value.name })
      setAssets({})
      await Promise.all([
        client.invalidateQueries({ queryKey: ['session'] }),
        client.invalidateQueries({ queryKey: ['platform', 'settings'] }),
        client.invalidateQueries({ queryKey: ['platform', 'mail-preview'] }),
      ])
      toast.success(
        value.identity_status === 'applied'
          ? '品牌已应用'
          : '品牌已保存，登录页正在同步'
      )
    },
  })
  async function select(slot: BrandSlot, file?: File) {
    if (!file) return
    setUploadError(null)
    if (
      !['image/png', 'image/webp', 'image/jpeg'].includes(file.type) ||
      file.size > 2 * 1024 * 1024
    ) {
      setUploadError(
        new Error('请选择不超过 2 MB 的静态 PNG、JPG 或 WebP 图片')
      )
      return
    }
    setReading(true)
    try {
      const url = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(new Error('图片读取失败'))
        reader.readAsDataURL(file)
      })
      const image = new Image()
      image.src = url
      await image.decode()
      if (image.naturalWidth * image.naturalHeight > 16_000_000)
        throw new Error('请选择不超过 1600 万像素的图片')
      setAssets((values) => ({
        ...values,
        [slot]: {
          content: url.split(',')[1],
          url,
          width: image.naturalWidth,
          height: image.naturalHeight,
        },
      }))
    } catch (error) {
      setUploadError(error)
    } finally {
      setReading(false)
    }
  }
  const busy = save.isPending || reading
  return (
    <div className='flex w-full max-w-5xl flex-col gap-6'>
      <Alert>
        <AlertTitle>一次设置，统一应用</AlertTitle>
        <AlertDescription>
          网页标题、导航、登录页、门户、下载页和新邮件共用品牌资料。选择图片后先预览，点击“保存并应用”才会生效。
        </AlertDescription>
      </Alert>
      {latest.revision !== saved.revision && (
        <Alert>
          <AlertTitle>品牌已由其他管理员更新</AlertTitle>
          <AlertDescription>
            当前草稿已保留。重新载入会放弃当前草稿，请先保留需要的修改。
            <Button
              type='button'
              variant='outline'
              disabled={busy}
              onClick={() => {
                setSaved(latest)
                form.reset({ platform_name: latest.name })
                setAssets({})
                save.reset()
              }}
            >
              重新载入品牌
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <Form {...form}>
        <form
          className='flex flex-col gap-6'
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
        >
          <Card>
            <CardHeader>
              <CardTitle>平台名称</CardTitle>
              <CardDescription>
                用于页面标题、登录提示与邮件。不会更改组织名称或登录地址。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FormField
                control={form.control}
                name='platform_name'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>平台名称</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        maxLength={80}
                        disabled={busy}
                        autoComplete='organization'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>品牌素材</CardTitle>
              <CardDescription>
                推荐透明 PNG，兼容静态 JPG、WebP；每张最大 2 MB、1600
                万像素。保持原比例，不裁切，最长边超过 2048 像素会等比缩小。
              </CardDescription>
            </CardHeader>
            <CardContent className='grid gap-6 md:grid-cols-2'>
              {slots.map(({ slot, title, hint }) => (
                <div key={slot} className='flex min-w-0 flex-col gap-3'>
                  <Label htmlFor={`brand-${slot}`}>{title}</Label>
                  <div
                    data-tone={slot.endsWith('_dark') ? 'dark' : 'light'}
                    className='brand-preview flex h-24 items-center justify-center rounded-md border bg-background p-3 text-foreground'
                  >
                    {preview.assets[slot] ? (
                      <img
                        src={preview.assets[slot]}
                        alt={title}
                        className='max-h-full max-w-full object-contain'
                      />
                    ) : (
                      <span className='text-sm text-muted-foreground'>
                        使用默认组合
                      </span>
                    )}
                  </div>
                  <p
                    id={`brand-${slot}-hint`}
                    className='text-sm text-muted-foreground'
                  >
                    {hint}
                  </p>
                  <Input
                    id={`brand-${slot}`}
                    type='file'
                    accept='image/png,image/jpeg,image/webp'
                    disabled={busy}
                    aria-describedby={`brand-${slot}-hint`}
                    onChange={(event) => {
                      void select(slot, event.target.files?.[0])
                      event.target.value = ''
                    }}
                  />
                  {assets[slot] && (
                    <p className='text-xs text-muted-foreground'>
                      {assets[slot].width} × {assets[slot].height} · 保存后应用
                    </p>
                  )}
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={busy || !preview.assets[slot]}
                    onClick={() =>
                      setAssets((values) => ({ ...values, [slot]: null }))
                    }
                  >
                    移除{title.split(' · ')[0]}
                    {slot.includes('dark') ? '深色版' : ''}
                  </Button>
                </div>
              ))}
              {!!uploadError && <RequestError error={uploadError} />}
            </CardContent>
          </Card>
          <BrandPreview brand={preview} smallIcon={smallIcon} />
          <Card>
            <CardHeader>
              <CardTitle>应用状态</CardTitle>
              <CardDescription>
                {dirty ? '当前为未保存预览。' : '当前显示已保存品牌。'}
              </CardDescription>
            </CardHeader>
            <CardContent className='flex flex-col gap-2 text-sm'>
              <p>网页与平台邮件：{dirty ? '保存后应用' : '已应用'}</p>
              <p role='status'>
                身份登录与身份邮件：
                {dirty
                  ? '保存后同步'
                  : latest.revision === saved.revision &&
                      latest.identity_status === 'applied'
                    ? '已同步'
                    : '等待同步，系统会自动重试'}
              </p>
              <p className='text-muted-foreground'>
                桌面内部品牌由客户端刷新资料后应用；系统 Dock
                和安装器图标需客户端打包支持。
              </p>
              {save.isError && (
                <RequestError
                  error={save.error}
                  retry={() =>
                    void client.invalidateQueries({
                      queryKey: ['platform', 'branding-settings'],
                    })
                  }
                />
              )}
            </CardContent>
            <CardFooter className='flex flex-wrap justify-between gap-3'>
              <Button
                type='button'
                variant='ghost'
                disabled={busy}
                onClick={() => {
                  form.setValue('platform_name', 'Actvero', {
                    shouldDirty: true,
                    shouldValidate: true,
                  })
                  setAssets(
                    Object.fromEntries(brandSlots.map((slot) => [slot, null]))
                  )
                }}
              >
                <RotateCcw data-icon='inline-start' />
                恢复默认品牌
              </Button>
              <div className='flex gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={busy || !dirty}
                  onClick={() => {
                    form.reset({ platform_name: saved.name })
                    setAssets({})
                    setUploadError(null)
                    save.reset()
                  }}
                >
                  取消更改
                </Button>
                <Button
                  type='submit'
                  disabled={
                    busy ||
                    !dirty ||
                    !isValid ||
                    latest.revision !== saved.revision
                  }
                >
                  <Save data-icon='inline-start' />
                  {save.isPending ? '应用中…' : '保存并应用'}
                </Button>
              </div>
            </CardFooter>
          </Card>
        </form>
      </Form>
    </div>
  )
}

function BrandPreview({
  brand,
  smallIcon,
}: {
  brand: Branding
  smallIcon: string
}) {
  const [tone, setTone] = useState<'light' | 'dark'>('light')
  return (
    <Card>
      <CardHeader>
        <CardTitle>应用预览</CardTitle>
        <CardDescription>
          图标按实际小尺寸展示；横版 Logo 已含名称时不会重复叠加文字。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs
          value={tone}
          onValueChange={(value) => setTone(value as 'light' | 'dark')}
        >
          <TabsList aria-label='预览背景'>
            <TabsTrigger value='light'>浅色背景</TabsTrigger>
            <TabsTrigger value='dark'>深色背景</TabsTrigger>
          </TabsList>
        </Tabs>
        <div
          className='brand-preview mt-4 rounded-md bg-background p-4 text-foreground'
          data-tone={tone}
        >
          <Tabs defaultValue='web'>
            <TabsList>
              <TabsTrigger value='web'>网页与导航</TabsTrigger>
              <TabsTrigger value='login'>登录与邮件</TabsTrigger>
            </TabsList>
            <TabsContent value='web' className='flex flex-col gap-4'>
              <div className='flex items-center gap-2 rounded-md border p-3'>
                <img src={smallIcon} alt='' className='size-4 object-contain' />
                <span className='truncate text-sm'>
                  品牌形象 · {brand.name}
                </span>
              </div>
              <div className='grid gap-4 sm:grid-cols-2'>
                <Card>
                  <CardHeader>
                    <CardDescription>展开导航 / 门户与下载</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <BrandLockup brand={brand} tone={tone} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardDescription>折叠导航 / 小尺寸图标</CardDescription>
                  </CardHeader>
                  <CardContent className='flex items-center gap-5'>
                    <BrandMark brand={brand} tone={tone} />
                    <img
                      src={smallIcon}
                      alt='32 像素预览'
                      className='size-8 object-contain'
                    />
                    <img
                      src={smallIcon}
                      alt='16 像素预览'
                      className='size-4 object-contain'
                    />
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
            <TabsContent value='login' className='grid gap-4 sm:grid-cols-2'>
              <Card>
                <CardHeader>
                  <BrandLockup brand={brand} tone={tone} />
                  <CardTitle>登录 {brand.name}</CardTitle>
                  <CardDescription>使用你的账号继续。</CardDescription>
                </CardHeader>
                <CardContent className='text-sm text-muted-foreground'>
                  登录、找回密码与账号确认使用同一套品牌。
                </CardContent>
              </Card>
              <Card data-tone='light' className='brand-preview'>
                <CardHeader>
                  <BrandLockup brand={brand} tone='light' />
                  <CardTitle>组织开通邀请</CardTitle>
                  <CardDescription>
                    {brand.name} 邀请你加入工作空间。
                  </CardDescription>
                </CardHeader>
                <CardContent className='text-sm text-muted-foreground'>
                  邮件使用浅色背景版本，名称与发信显示名同步。
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </CardContent>
    </Card>
  )
}
