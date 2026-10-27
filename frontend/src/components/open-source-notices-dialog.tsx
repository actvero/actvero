import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export function OpenSourceNoticesDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>开源声明</DialogTitle>
          <DialogDescription>
            渠道与模型管理界面基于 New API，已适配 Actvero。
          </DialogDescription>
        </DialogHeader>
        <p className='text-sm'>
          Frontend design and development by New API contributors.
        </p>
        <a
          className='text-sm underline underline-offset-4'
          href='https://github.com/QuantumNous/new-api'
          target='_blank'
          rel='noreferrer'
        >
          New API 原始项目
        </a>
      </DialogContent>
    </Dialog>
  )
}
