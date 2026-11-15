import { ApiError } from '@/lib/api'

export type ReaderCredentials = { token: string; parentOrigin: string }
export type ReaderEvent =
  | { type: 'page'; page: number }
  | { type: 'loaded'; documentId: string }

export function readerHeaders(credentials?: ReaderCredentials): HeadersInit {
  return credentials
    ? {
        Authorization: `Bearer ${credentials.token}`,
        'X-Knowledge-Parent': credentials.parentOrigin,
      }
    : {}
}

export async function readerFetch(
  url: string,
  credentials?: ReaderCredentials,
  signal?: AbortSignal
) {
  // The manifest only supplies same-service endpoints, never arbitrary remote file URLs.
  if (
    !url.startsWith('/api/v1/knowledge/') &&
    url !== '/api/v1/knowledge-reader/source'
  )
    throw new Error('原文地址无效')
  const response = await fetch(url, {
    signal,
    credentials: credentials ? 'omit' : 'same-origin',
    headers: readerHeaders(credentials),
    redirect: 'error',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(
      response.status,
      error?.error?.message ?? '原件读取失败，请重新打开'
    )
  }
  return response
}

export const readerProtocol = 'actvero.knowledge.v1'
export function trustedParent(value: string) {
  try {
    const url = new URL(value)
    if (
      url.origin !== value ||
      !['https:', 'http:'].includes(url.protocol) ||
      url.username ||
      url.password ||
      (url.protocol === 'http:' &&
        !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
    )
      return null
    return url.origin
  } catch {
    return null
  }
}
