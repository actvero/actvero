import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Expand, X } from 'lucide-react'
import { ApiError, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { LoadingState, RequestError } from '@/components/request-state'
import { OriginalViewer } from './original-viewer'
import {
  readerHeaders,
  readerProtocol,
  trustedParent,
  type ReaderEvent,
} from './reader-http'
import { ChunkTranscript, ReaderLayout, ReaderToolbar } from './reader-layout'
import { locationLabel } from './shared'

export function EmbeddedReader({ parentOrigin }: { parentOrigin: string }) {
  const parent = trustedParent(parentOrigin)
  if (!parent)
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>嵌入来源无效</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  return <ReaderSession key={parent} parent={parent} />
}

function ReaderSession({ parent }: { parent: string }) {
  const [token, setToken] = useState('')
  const [failure, setFailure] = useState<unknown>()
  const send = useCallback(
    (type: string, payload: object = {}) => {
      if (parent && window.parent !== window)
        window.parent.postMessage(
          { protocol: readerProtocol, type, ...payload },
          parent
        )
    },
    [parent]
  )
  const unavailable = useCallback(
    (cause: unknown) => {
      setToken('')
      setFailure(cause)
      send('error', { code: 'reader_unavailable' })
    },
    [send]
  )
  useEffect(() => {
    if (!parent || window.parent === window) return
    const receive = (event: MessageEvent) => {
      if (
        event.source !== window.parent ||
        event.origin !== parent ||
        event.data?.protocol !== readerProtocol
      )
        return
      if (
        event.data.type === 'init' &&
        typeof event.data.token === 'string' &&
        event.data.token.startsWith('avr_') &&
        event.data.token.length <= 4096
      ) {
        setFailure(undefined)
        setToken(event.data.token)
      }
      if (event.data.type === 'clear') {
        setFailure(undefined)
        setToken('')
      }
    }
    window.addEventListener('message', receive)
    window.parent.postMessage(
      { protocol: readerProtocol, type: 'ready' },
      parent
    )
    return () => window.removeEventListener('message', receive)
  }, [parent])
  const tools = (
    <>
      <Button
        variant='ghost'
        size='icon-xs'
        aria-label='请求展开原文'
        onClick={() => send('expand')}
      >
        <Expand />
      </Button>
      <Button
        variant='ghost'
        size='icon-xs'
        aria-label='请求关闭原文'
        onClick={() => {
          setToken('')
          setFailure(undefined)
          send('close')
        }}
      >
        <X />
      </Button>
    </>
  )
  return (
    <main className='flex h-dvh min-h-0 flex-col bg-background'>
      <h1 className='sr-only'>原文预览</h1>
      {token ? (
        <AuthorizedOriginal
          key={token}
          token={token}
          parent={parent}
          send={send}
          tools={tools}
          unavailable={unavailable}
        />
      ) : (
        <>
          <ReaderToolbar
            toolbar={{
              filename: '原文预览',
              trailing: failure != null ? tools : undefined,
            }}
          />
          {failure != null ? (
            <div className='p-6'>
              <RequestError error={failure} />
            </div>
          ) : (
            <Empty className='flex-1'>
              <EmptyHeader>
                <EmptyTitle>等待打开原文</EmptyTitle>
              </EmptyHeader>
            </Empty>
          )}
        </>
      )}
    </main>
  )
}

function AuthorizedOriginal({
  token,
  parent,
  send,
  tools,
  unavailable,
}: {
  token: string
  parent: string
  send: (type: string, payload?: object) => void
  tools: React.ReactNode
  unavailable: (cause: unknown) => void
}) {
  const [jump, setJump] = useState(0)
  const [instance] = useState(() => crypto.randomUUID())
  const credentials = { token, parentOrigin: parent }
  // Credentials must not enter the query cache key; a unique component instance isolates each token.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    // The token stays in this component's memory and never enters URLs or query keys.
    // Credentials are intentionally excluded; instance is unique for each token-mounted component.
    queryKey: ['knowledge-reader', parent, instance],
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
    queryFn: async ({ signal }): Promise<Schema['ReaderManifest']> => {
      const response = await fetch('/api/v1/knowledge-reader/manifest', {
        signal,
        credentials: 'omit',
        headers: readerHeaders(credentials),
        redirect: 'error',
      })
      const body = await response.json().catch(() => null)
      if (!response.ok)
        throw new ApiError(
          response.status,
          body?.error?.message ?? '原文预览已失效，请重新打开'
        )
      if (
        !body?.document_id ||
        !body.generation_id ||
        !body.citation_id ||
        body.source_url !== '/api/v1/knowledge-reader/source' ||
        typeof body.chunk?.content !== 'string' ||
        !Number.isInteger(body.chunk.sequence)
      )
        throw new ApiError(422, '阅读凭证对应的文档版本或切片无效')
      return body
    },
  })
  useEffect(() => {
    if (query.isError) unavailable(query.error)
  }, [query.isError, query.error, unavailable])
  if (query.isPending || query.isError)
    return (
      <>
        <ReaderToolbar toolbar={{ filename: '原文预览', trailing: tools }} />
        {query.isPending ? (
          <LoadingState />
        ) : (
          <div className='p-6'>
            <RequestError error={query.error} />
          </div>
        )}
      </>
    )
  const data = query.data
  const event = (value: ReaderEvent) =>
    send(
      value.type,
      value.type === 'page'
        ? { page: value.page }
        : { documentId: value.documentId }
    )
  return (
    <ReaderLayout
      label='引用切片'
      toggleLabel='切片正文'
      initialOpen={false}
      tools={tools}
      original={(trailing) => (
        <OriginalViewer
          preview={data}
          credentials={credentials}
          onEvent={event}
          onReadError={unavailable}
          jump={jump}
          toolbar={{ filename: data.filename, trailing }}
        />
      )}
      sidebar={
        <ChunkTranscript
          content={data.chunk.content}
          location={data.sources?.[0] && locationLabel(data.sources[0])}
          onLocate={() => setJump((value) => value + 1)}
        />
      }
    />
  )
}
