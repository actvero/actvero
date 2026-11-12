import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { ArrowLeft, X } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { OriginalViewer } from './original-viewer'
import { useKnowledge, type Citation } from './shared'

export const readerDialogClass =
  'flex h-dvh w-screen max-w-none flex-col gap-0 rounded-none border-0 p-0 sm:max-w-none'

export function SourceDialog({
  citation,
  onClose,
}: {
  citation: Citation | null
  onClose: () => void
}) {
  return (
    <Dialog
      open={!!citation}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className={readerDialogClass}
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <header className='flex h-16 shrink-0 items-center gap-3 border-b px-4'>
          <Button
            variant='ghost'
            size='icon'
            aria-label='返回检索结果'
            onClick={onClose}
          >
            <ArrowLeft />
          </Button>
          <DialogTitle className='min-w-0 flex-1 truncate'>
            {citation?.filename ?? '原文预览'}
          </DialogTitle>
          <Button
            variant='ghost'
            size='icon'
            aria-label='关闭原文预览'
            onClick={onClose}
          >
            <X />
          </Button>
        </header>
        {citation && (
          <div className='min-h-0 flex-1'>
            <SourcePreview citation={citation} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function SourcePreview({ citation }: { citation: Citation }) {
  return (
    <DocumentOriginal
      baseId={citation.base_id}
      documentId={citation.document_id}
      generationId={citation.generation_id}
      chunkId={citation.id}
    />
  )
}

export function DocumentOriginal({
  baseId,
  documentId,
  generationId,
  chunkId,
}: {
  baseId: string
  documentId: string
  generationId?: string | null
  chunkId?: string
}) {
  const params = new URLSearchParams()
  if (generationId) params.set('generation_id', generationId)
  if (chunkId) params.set('chunk_id', chunkId)
  const { key } = useKnowledge()
  const path = `/knowledge/${baseId}/documents/${documentId}/preview?${params}`
  const query = useQuery({
    queryKey: [...key, 'preview', path],
    queryFn: ({ signal }) =>
      api<Schema['DocumentPreview']>(path, 'GET', undefined, undefined, signal),
    placeholderData: keepPreviousData,
  })
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <div className='p-6'>
        <RequestError error={query.error} />
      </div>
    )
  return <OriginalViewer preview={query.data} />
}
