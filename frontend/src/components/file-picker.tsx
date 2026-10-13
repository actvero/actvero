import { useRef } from 'react'
import { FolderOpen, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function FilePicker({
  disabled,
  onFiles,
}: {
  disabled?: boolean
  onFiles: (files: File[], folder: boolean) => void
}) {
  const zip = useRef<HTMLInputElement>(null)
  const folder = useRef<HTMLInputElement>(null)
  return (
    <div className='flex flex-wrap justify-center gap-2'>
      <Button
        type='button'
        variant='outline'
        disabled={disabled}
        onClick={() => zip.current?.click()}
      >
        <Upload />
        选择 ZIP
      </Button>
      <Button
        type='button'
        variant='outline'
        disabled={disabled}
        onClick={() => folder.current?.click()}
      >
        <FolderOpen />
        选择文件夹
      </Button>
      <Input
        ref={zip}
        type='file'
        accept='.zip,application/zip'
        className='sr-only'
        tabIndex={-1}
        aria-label='上传 ZIP 文件'
        disabled={disabled}
        onChange={(e) => {
          if (e.target.files?.length) onFiles([...e.target.files], false)
          e.target.value = ''
        }}
      />
      <Input
        ref={folder}
        type='file'
        {...{ webkitdirectory: '' }}
        multiple
        className='sr-only'
        tabIndex={-1}
        aria-label='上传技能文件夹'
        disabled={disabled}
        onChange={(e) => {
          if (e.target.files?.length) onFiles([...e.target.files], true)
          e.target.value = ''
        }}
      />
    </div>
  )
}
