import { retryAfterUntil } from './retry-after'
import type { components } from './schema'

export type Schema = components['schemas']
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public references?: Schema['ChannelRemovalReference'][],
    public retryAfterUntil?: number
  ) {
    super(message)
  }
}
export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  csrf?: string,
  signal?: AbortSignal
): Promise<T> {
  const multipart = body instanceof FormData
  const binary = body instanceof Blob
  const response = await fetch('/api/v1' + path, {
    method,
    credentials: 'same-origin',
    signal,
    headers: {
      ...(body === undefined || multipart
        ? {}
        : {
            'Content-Type': binary
              ? 'application/octet-stream'
              : 'application/json',
          }),
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    },
    body:
      body === undefined
        ? undefined
        : multipart || binary
          ? body
          : JSON.stringify(body),
  })
  const result = await response.json().catch(() => null)
  if (!response.ok)
    throw new ApiError(
      response.status,
      result?.error?.message ?? '请求失败，请稍后重试',
      Array.isArray(result?.error?.references)
        ? result.error.references
        : undefined,
      retryAfterUntil(
        response.headers.get('Retry-After'),
        response.headers.get('Date')
      )
    )
  return result as T
}
export const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : '操作失败，请稍后重试'
export const dateTime = (value: string) =>
  new Date(value).toLocaleString('zh-CN', { hour12: false })
