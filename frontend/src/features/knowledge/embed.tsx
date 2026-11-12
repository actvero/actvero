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

export function EmbeddedReader({ parentOrigin }: { parentOrigin: string }) {
  const parent = trustedParent(parentOrigin)
  const [token, setToken] = useState('')
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
      )
        setToken(event.data.token)
      if (event.data.type === 'clear') setToken('')
    }
    window.addEventListener('message', receive)
    window.parent.postMessage(
      { protocol: readerProtocol, type: 'ready' },
      parent
    )
    return () => window.removeEventListener('message', receive)
  }, [parent])
  if (!parent)
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>嵌入来源无效</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  return (
    <main className='flex h-dvh min-h-0 flex-col bg-background'>
      <header className='flex h-14 shrink-0 items-center justify-between gap-3 border-b px-4'>
        <h1 className='font-semibold'>原文预览</h1>
        <div className='flex gap-1'>
          <Button
            variant='ghost'
            size='icon'
            aria-label='请求展开原文'
            onClick={() => send('expand')}
          >
            <Expand />
          </Button>
          <Button
            variant='ghost'
            size='icon'
            aria-label='请求关闭原文'
            onClick={() => {
              setToken('')
              send('close')
            }}
          >
            <X />
          </Button>
        </div>
      </header>
      {token ? (
        <AuthorizedOriginal
          key={token}
          token={token}
          parent={parent}
          send={send}
        />
      ) : (
        <Empty className='flex-1'>
          <EmptyHeader>
            <EmptyTitle>等待打开原文</EmptyTitle>
          </EmptyHeader>
        </Empty>
      )}
    </main>
  )
}

function AuthorizedOriginal({
  token,
  parent,
  send,
}: {
  token: string
  parent: string
  send: (type: string, payload?: object) => void
}) {
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
    queryFn: async ({ signal }): Promise<Schema['DocumentPreview']> => {
      const response = await fetch('/api/v1/knowledge-reader/manifest', {
        signal,
        credentials: 'omit',
        headers: readerHeaders(credentials),
        redirect: 'error',
      })
      const body = await response.json()
      if (!response.ok)
        throw new ApiError(
          response.status,
          body.error?.message ?? '原文预览已失效，请重新打开'
        )
      return body
    },
  })
  useEffect(() => {
    if (query.isError) send('error', { code: 'reader_unavailable' })
  }, [query.isError, send])
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <div className='p-6'>
        <RequestError error={query.error} />
      </div>
    )
  const event = (value: ReaderEvent) =>
    send(
      value.type,
      value.type === 'page'
        ? { page: value.page }
        : { documentId: value.documentId }
    )
  return (
    <>
      <div className='truncate border-b px-4 py-2 text-sm text-muted-foreground'>
        {query.data.filename}
      </div>
      <div className='min-h-0 flex-1'>
        <OriginalViewer
          preview={query.data}
          credentials={credentials}
          onEvent={event}
        />
      </div>
    </>
  )
}
