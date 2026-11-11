import { useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { FileArchive, LoaderCircle, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RequestError } from '@/components/request-state'
import { packageSize, useWorkbenches, type Workbench } from './shared'

export function UploadWorkbenchDialog({
  workbench,
  onUploaded,
}: {
  workbench?: Workbench
  onUploaded?: (result: Workbench) => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File>()
  const [fileError, setFileError] = useState('')
  const { csrf, update } = useWorkbenches()
  const upload = useMutation({
    mutationFn: (value: File) =>
      api<Workbench>(
        workbench
          ? `/workbenches/${workbench.id}/versions?revision=${workbench.revision}`
          : '/workbenches',
        'POST',
        value,
        csrf
      ),
    onSuccess: (result) => {
      update(result)
      setOpen(false)
      setFile(undefined)
      toast.success('已校验安装包并保存为草稿')
      onUploaded?.(result)
    },
  })
  function changeOpen(value: boolean) {
    if (upload.isPending) return
    setOpen(value)
    if (!value) {
      setFile(undefined)
      setFileError('')
      upload.reset()
    }
  }
  const title = workbench ? '上传新版本' : '上传工作台'
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button>
          <Upload />
          {title}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {workbench
              ? `新版本的包名须为 ${workbench.package_name}。`
              : '从 Actvero 工作台构建产物创建草稿。'}
          </DialogDescription>
        </DialogHeader>
        <form
          className='flex min-w-0 flex-col gap-4'
          onSubmit={(event) => {
            event.preventDefault()
            if (file && !fileError && !upload.isPending) upload.mutate(file)
          }}
        >
          <Field data-invalid={!!fileError}>
            <FieldLabel htmlFor={id}>工作台安装包</FieldLabel>
            <Input
              id={id}
              type='file'
              accept='.tgz,application/gzip,application/x-gzip'
              aria-describedby={`${id}-help`}
              aria-invalid={!!fileError}
              disabled={upload.isPending}
              onChange={(event) => {
                const next = event.target.files?.[0]
                setFile(next)
                upload.reset()
                setFileError(
                  next && !next.name.toLowerCase().endsWith('.tgz')
                    ? '请选择 .tgz 工作台安装包'
                    : next && (next.size === 0 || next.size > 8 * 1024 * 1024)
                      ? '请选择不超过 8 MiB 的非空安装包'
                      : ''
                )
              }}
            />
            <FieldDescription id={`${id}-help`}>
              {fileError ||
                '支持 .tgz，最大 8 MiB。上传后校验包结构并保存为草稿。'}
            </FieldDescription>
          </Field>
          {file && !fileError && (
            <div className='flex min-w-0 items-center gap-3 rounded-md border p-3 text-sm'>
              <FileArchive
                className='size-5 shrink-0 text-muted-foreground'
                aria-hidden='true'
              />
              <span className='min-w-0 flex-1 truncate'>{file.name}</span>
              <span className='shrink-0 text-muted-foreground'>
                {packageSize(file.size)}
              </span>
            </div>
          )}
          {upload.isError && <RequestError error={upload.error} />}
          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              disabled={upload.isPending}
              onClick={() => changeOpen(false)}
            >
              取消
            </Button>
            <Button
              type='submit'
              disabled={!file || !!fileError || upload.isPending}
            >
              {upload.isPending && <LoaderCircle className='animate-spin' />}
              {upload.isPending ? '校验中…' : '上传并校验'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
