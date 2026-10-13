import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate } from '@tanstack/react-router'
import { zip } from 'fflate'
import { PackageCheck, PackageOpen } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { FilePicker } from '@/components/file-picker'
import { PageShell } from '@/components/layout/page-shell'
import { Markdown } from '@/components/markdown'
import { RequestError } from '@/components/request-state'
import { metadataSchema, type Metadata } from './form-schema'
import { MetadataFields } from './metadata-fields'
import { binaryRequest, sizeLabel, useSkills, type Skill } from './shared'

const versionSchema = z.object({
  version: z
    .string()
    .max(50)
    .regex(
      /^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$/,
      '请使用 1.0.0 格式的版本号'
    ),
  release_notes: z.string().max(4000),
})
type VersionInput = z.infer<typeof versionSchema>
async function folderZip(files: File[]) {
  if (
    files.length > 500 ||
    files.reduce((sum, f) => sum + f.size, 0) > 40 * 1024 * 1024 ||
    files.some((f) => f.size > 5 * 1024 * 1024)
  )
    throw new Error('最多 500 个文件，单文件 5 MB，总大小 40 MB')
  const entries: Record<string, Uint8Array> = Object.create(null)
  for (const file of files)
    entries[file.webkitRelativePath || file.name] = new Uint8Array(
      await file.arrayBuffer()
    )
  const zipped = await new Promise<Uint8Array<ArrayBuffer>>((resolve, reject) =>
    zip(entries, (err, data) =>
      err ? reject(err) : resolve(new Uint8Array(data))
    )
  )
  return new Blob([zipped], { type: 'application/zip' })
}
function toBase64(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsDataURL(blob)
  })
}
export function UploadWizard({
  close,
  skill,
}: {
  close: () => void
  skill?: Skill
}) {
  const { csrf, refresh } = useSkills()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const [preview, setPreview] = useState<Schema['SkillPreview']>()
  const [blob, setBlob] = useState<Blob>()
  const [filename, setFilename] = useState('')
  const [step, setStep] = useState(1)
  const versionForm = useForm<VersionInput>({
    resolver: zodResolver(versionSchema),
    defaultValues: { version: skill ? '' : '1.0.0', release_notes: '' },
  })
  const form = useForm<Metadata>({
    resolver: zodResolver(metadataSchema),
    defaultValues: skill
      ? {
          display_name: skill.display_name,
          description: skill.description,
          category: skill.category ?? 'uncategorized',
          audience: skill.audience,
          member_ids: skill.member_ids,
        }
      : {
          display_name: '',
          description: '',
          category: 'uncategorized',
          member_ids: [],
        },
  })
  async function choose(files: File[], folder: boolean) {
    setError(undefined)
    setPreview(undefined)
    setBlob(undefined)
    setBusy(true)
    try {
      const value = folder ? await folderZip(files) : files[0]
      if (value.size > 20 * 1024 * 1024)
        throw new Error('技能 ZIP 不能超过 20 MB')
      const result = await binaryRequest('/preview', csrf, value)
      const data = (await result.json()) as Schema['SkillPreview']
      if (skill && data.name !== skill.name)
        throw new Error(`技能 name 必须为 ${skill.name}`)
      setBlob(value)
      setPreview(data)
      setFilename(
        folder ? files[0].webkitRelativePath.split('/')[0] : files[0].name
      )
      if (!skill) {
        form.setValue('display_name', data.name)
        form.setValue('description', data.description)
      }
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  async function save(values: Metadata) {
    if (!blob || !preview) return
    setError(undefined)
    setBusy(true)
    try {
      const result = await api<Skill>(
        '/skills/import',
        'POST',
        {
          ...values,
          ...versionForm.getValues(),
          skill_id: skill?.id,
          revision: skill?.revision,
          package_base64: await toBase64(blob),
        },
        csrf
      )
      await refresh()
      toast.success('技能草稿已保存，可在详情中发布')
      await navigate({ to: '/skills/$skillId', params: { skillId: result.id } })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <PageShell
      title={skill ? '上传新版本' : '上传技能'}
      description={`第 ${step} / 2 步 · 检查后保存草稿，在详情中确认发布。`}
      action={
        <Button variant='outline' disabled={busy} onClick={close}>
          取消上传
        </Button>
      }
    >
      <div className='mx-auto w-full max-w-3xl'>
        {step === 1 ? (
          <Form {...versionForm}>
            <form
              className='space-y-5'
              onSubmit={versionForm.handleSubmit(() => {
                if (preview) {
                  setStep(2)
                  setError(undefined)
                }
              })}
            >
              <Card>
                <CardContent className='space-y-4 py-4 text-center'>
                  <PackageOpen className='mx-auto size-8 text-muted-foreground' />
                  <p>上传包含 SKILL.md 的 ZIP 或文件夹</p>
                  <p className='text-sm text-muted-foreground'>
                    ZIP ≤ 20 MB · 单文件 ≤ 5 MB · 最多 500 个文件
                  </p>
                  <FilePicker
                    disabled={busy}
                    onFiles={(files, folder) => void choose(files, folder)}
                  />
                  {busy && <p role='status'>正在检查技能包…</p>}
                </CardContent>
              </Card>
              {preview && (
                <div className='flex items-center gap-2 text-sm'>
                  <PackageCheck className='size-4' />
                  <span className='break-all'>
                    {filename} · {preview.files.length} 个文件 ·{' '}
                    {sizeLabel(preview.size)}
                  </span>
                </div>
              )}
              <FormField
                control={versionForm.control}
                name='version'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>版本号</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder='例如 1.0.0'
                        maxLength={50}
                        disabled={busy}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={versionForm.control}
                name='release_notes'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>更新说明（可选）</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        rows={3}
                        maxLength={4000}
                        disabled={busy}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {error != null && <RequestError error={error} />}
              <div className='flex justify-end gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={busy}
                  onClick={close}
                >
                  取消
                </Button>
                <Button disabled={busy || !preview}>下一步：预览与设置</Button>
              </div>
            </form>
          </Form>
        ) : (
          <Form {...form}>
            <form className='space-y-5' onSubmit={form.handleSubmit(save)}>
              <div className='space-y-1'>
                <p className='font-medium'>
                  {preview?.name} · v{versionForm.getValues('version')}
                </p>
                <p className='text-sm text-muted-foreground'>来源：SKILL.md</p>
              </div>
              <Card>
                <CardContent className='max-h-64 overflow-y-auto'>
                  <Markdown>{preview?.skill_md || '此技能尚无正文。'}</Markdown>
                </CardContent>
              </Card>
              {!skill && (
                <MetadataFields
                  form={form}
                  disabled={busy}
                  packageIcon={preview?.package_icon}
                  iconWarning={preview?.icon_warning}
                />
              )}
              {preview?.icon_warning && (
                <p role='status' className='text-sm text-muted-foreground'>
                  {preview.icon_warning}
                </p>
              )}
              {skill && (
                <p className='text-sm text-muted-foreground'>
                  新版本沿用技能的展示资料和使用范围；保存草稿不会替换生效版本。
                </p>
              )}
              {error != null && <RequestError error={error} />}
              <div className='flex justify-end gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={busy}
                  onClick={() => setStep(1)}
                >
                  上一步
                </Button>
                <Button disabled={busy}>{busy ? '保存中…' : '保存草稿'}</Button>
              </div>
            </form>
          </Form>
        )}
      </div>
    </PageShell>
  )
}
