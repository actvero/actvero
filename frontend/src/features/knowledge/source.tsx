import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { OriginalViewer } from './original-viewer'
import {
  ChunkTranscript,
  ReaderLayout,
  ReaderToolbar,
  type Toolbar,
} from './reader-layout'
import { locationLabel, useKnowledge, type Citation } from './shared'

export const readerDialogClass =
  'flex h-dvh w-screen max-w-none flex-col gap-0 overflow-hidden rounded-none border-0 p-0 sm:max-w-none'

export function SourceDialog({
  citation,
  onClose,
}: {
  citation: Citation | null
  onClose: () => void
}) {
  const [jump, setJump] = useState(0)
  return (
    <Dialog
      open={!!citation}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className={readerDialogClass}
        motion='fade'
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <DialogTitle className='sr-only'>
          {citation?.filename ?? '原文预览'}
        </DialogTitle>
        {citation && (
          <ReaderLayout
            key={citation.id}
            label='引用切片'
            toggleLabel='切片正文'
            initialOpen={false}
            original={(trailing) => (
              <DocumentOriginal
                baseId={citation.base_id}
                documentId={citation.document_id}
                generationId={citation.generation_id}
                chunkId={citation.id}
                jump={jump}
                toolbar={{
                  filename: citation.filename,
                  back: { label: '返回检索结果', action: onClose },
                  trailing,
                }}
              />
            )}
            sidebar={
              <ChunkTranscript
                content={citation.content}
                location={
                  citation.sources[0] && locationLabel(citation.sources[0])
                }
                onLocate={() => setJump((value) => value + 1)}
              />
            }
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export function DocumentOriginal({
  baseId,
  documentId,
  generationId,
  chunkId,
  toolbar,
  jump,
  highlights,
}: {
  baseId: string
  documentId: string
  generationId?: string | null
  chunkId?: string
  toolbar: Toolbar
  jump?: number
  highlights?: Pick<Schema['DocumentPreview'], 'sources' | 'text_ranges'>
}) {
  const params = new URLSearchParams()
  if (generationId) params.set('generation_id', generationId)
  if (chunkId) params.set('chunk_id', chunkId)
  const { key } = useKnowledge()
  const docPath = `/knowledge/${baseId}/documents/${documentId}`
  const path = `${docPath}/preview?${params}`
  const source = `/api/v1${docPath}/source`
  const query = useQuery({
    queryKey: [
      ...key,
      'preview',
      path,
      { documentId, generationId, chunkId, source },
    ],
    queryFn: async ({ signal }) => {
      const data = await api<Schema['DocumentPreview']>(
        path,
        'GET',
        undefined,
        undefined,
        signal
      )
      if (
        data.document_id !== documentId ||
        (generationId && generationId !== data.generation_id) ||
        (data.citation_id ?? undefined) !== chunkId ||
        data.source_url !== source
      )
        throw new Error('原文与所选文档版本或切片不匹配，请返回后重新打开')
      return data
    },
    placeholderData: keepPreviousData,
  })
  const preview =
    !query.isError &&
    query.data?.document_id === documentId &&
    (!generationId || query.data.generation_id === generationId) &&
    query.data.source_url === source
      ? query.data
      : undefined
  if (!preview)
    return (
      <div className='flex h-full min-h-0 flex-col'>
        <ReaderToolbar toolbar={toolbar} />
        {query.isError ? (
          <div className='p-6'>
            <RequestError error={query.error} />
          </div>
        ) : (
          <LoadingState />
        )}
      </div>
    )
  return (
    <OriginalViewer
      preview={highlights ? { ...preview, ...highlights } : preview}
      toolbar={toolbar}
      jump={query.isPlaceholderData ? 0 : jump}
    />
  )
}
