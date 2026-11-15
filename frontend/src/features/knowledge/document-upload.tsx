import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { LoaderCircle, Plus, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, messageOf } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useKnowledge } from './shared'

const accept = '.pdf,.png,.jpg,.jpeg,.txt,.md,.csv,.docx,.xlsx'
type UploadItem = { file: File; id: string }
type FailedUpload = UploadItem & { error: string }

export function UploadButton({
  baseId,
  onComplete,
  onUploadingChange,
  dropzone = false,
}: {
  baseId: string
  onComplete?: (successCount: number) => void
  onUploadingChange?: (uploading: boolean) => void
  dropzone?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const pending = useRef(false)
  const { csrf, refresh } = useKnowledge()
  const [failures, setFailures] = useState<FailedUpload[]>([])
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  const upload = useMutation({
    mutationFn: async (files: UploadItem[]) => {
      const failed: FailedUpload[] = []
      for (const [index, item] of files.entries()) {
        try {
          await api(
            `/knowledge/${baseId}/documents?filename=${encodeURIComponent(item.file.name)}&upload_id=${item.id}`,
            'POST',
            item.file,
            csrf
          )
        } catch (error) {
          failed.push({ ...item, error: messageOf(error) })
        }
        setProgress({ completed: index + 1, total: files.length })
      }
      return failed
    },
    onSuccess: (failed, files) => {
      const submitted = new Set(files.map(({ id }) => id))
      const remaining = [
        ...failures.filter(({ id }) => !submitted.has(id)),
        ...failed,
      ]
      setFailures(remaining)
      const successCount = files.length - failed.length
      if (successCount) {
        void refresh()
        toast.success(`已上传 ${successCount} 份文档，可在处理队列查看进度`)
        if (!remaining.length) onComplete?.(successCount)
      }
    },
    onSettled: () => {
      pending.current = false
      onUploadingChange?.(false)
    },
  })

  function start(files: UploadItem[]) {
    if (pending.current || !files.length) return
    pending.current = true
    setProgress({ completed: 0, total: files.length })
    onUploadingChange?.(true)
    upload.mutate(files)
  }

  function submitFiles(files: FileList | null) {
    if (files?.length) {
      start(Array.from(files, (file) => ({ file, id: crypto.randomUUID() })))
    }
  }

  function preventFileDrop(event: React.DragEvent) {
    if (event.dataTransfer.types.includes('Files')) event.preventDefault()
  }

  return (
    <div className='flex min-w-0 flex-col gap-3'>
      <div
        className={
          dropzone
            ? 'flex min-w-0 flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center'
            : 'flex flex-wrap items-center gap-2'
        }
        onDragOver={dropzone ? preventFileDrop : undefined}
        onDrop={
          dropzone
            ? (event) => {
                preventFileDrop(event)
                submitFiles(event.dataTransfer.files)
              }
            : undefined
        }
      >
        {dropzone && (
          <>
            <Upload className='mb-1 size-6 text-muted-foreground' aria-hidden />
            <p className='text-sm font-medium'>选择文件，或拖放到这里</p>
            <p className='mb-2 text-xs text-muted-foreground'>
              支持 PDF、PNG、JPEG、TXT、Markdown、CSV、DOCX、XLSX；单文件最多 20
              MiB
            </p>
          </>
        )}
        <input
          ref={input}
          hidden
          type='file'
          accept={accept}
          multiple
          aria-label='上传知识库文档'
          onChange={(event) => {
            submitFiles(event.target.files)
            event.target.value = ''
          }}
        />
        <Button
          type='button'
          disabled={upload.isPending}
          onClick={() => input.current?.click()}
        >
          {upload.isPending ? (
            <LoaderCircle
              className='motion-safe:animate-spin'
              data-icon='inline-start'
            />
          ) : (
            !dropzone && <Upload data-icon='inline-start' />
          )}
          {upload.isPending ? '正在上传…' : dropzone ? '选择文件' : '上传文档'}
        </Button>
        {upload.isPending && (
          <p role='status' className='text-xs text-muted-foreground'>
            已尝试上传 {progress.completed} / {progress.total} 个文件
          </p>
        )}
      </div>
      {failures.length > 0 && (
        <Alert variant='destructive' role='alert'>
          <AlertTitle>{failures.length} 个文件上传失败</AlertTitle>
          <AlertDescription className='min-w-0'>
            <ul className='flex max-h-44 flex-col gap-1 overflow-y-auto'>
              {failures.map(({ file, id, error }) => (
                <li key={id} className='wrap-anywhere'>
                  {file.name}：{error}
                </li>
              ))}
            </ul>
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={upload.isPending}
                onClick={() => start(failures)}
              >
                重试失败文件
              </Button>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                disabled={upload.isPending}
                onClick={() => setFailures([])}
              >
                忽略失败文件
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}

export function AddDocuments({ baseId }: { baseId: string }) {
  const [open, setOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!uploading) setOpen(next)
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus data-icon='inline-start' />
          上传文档
        </Button>
      </DialogTrigger>
      <DialogContent
        className='max-h-[calc(100svh-2rem)] overflow-y-auto'
        showCloseButton={false}
      >
        <DialogHeader>
          <DialogTitle>上传文档</DialogTitle>
          <DialogDescription>
            上传后自动开始处理。PDF 和图片会发送至配置的 MinerU 服务解析。
          </DialogDescription>
        </DialogHeader>
        <UploadButton
          baseId={baseId}
          dropzone
          onUploadingChange={setUploading}
          onComplete={() => setOpen(false)}
        />
        <DialogFooter>
          <DialogClose asChild>
            <Button variant='outline' disabled={uploading}>
              关闭
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
