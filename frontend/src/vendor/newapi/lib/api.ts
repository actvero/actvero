/* Actvero integration adapter. Native New API payloads stay unchanged.
 * See ../NOTICE and ../LICENSE for the upstream module's license. */
import axios, { type AxiosRequestConfig } from 'axios'
import type { AuthBundle } from '@newapi/stores/auth-store'

export interface ApiRequestConfig<D = unknown> extends AxiosRequestConfig<D> {
  disableDuplicate?: boolean
  skipBusinessError?: boolean
  skipErrorHandler?: boolean
}
let csrf = ''
let consoleUrl = ''
const channelSnapshots = new Map<number, { models: string; revision: string }>()
const editorRevisions = new Map<number, string>()
export function bindNativeChannelSnapshot(channel: {
  id: number
  models: string
  revision: string
}) {
  channelSnapshots.set(channel.id, {
    models: channel.models,
    revision: channel.revision,
  })
}
export function nativeConsoleUrl() {
  return consoleUrl
}
export function bindNativeSession(value: string, base = '') {
  csrf = value
  consoleUrl = base
  channelSnapshots.clear()
  editorRevisions.clear()
}
export const api = axios.create({
  baseURL: '/api/v1/model-gateway/native',
  withCredentials: true,
})
api.interceptors.request.use(async (config) => {
  // An administrator's Actvero session authorizes each native operation.
  // New API management tokens and supplier secrets never enter this adapter.
  const test = config.url?.match(/^\/api\/channel\/test\/(\d+)$/)
  const discovery = config.url?.match(/^\/api\/channel\/fetch_models\/(\d+)$/)
  if (config.method === 'get' && test) {
    // Native tests use GET upstream. Actvero exposes this billable operation
    // as a CSRF-protected mutation; the native dialog keeps its own UI contract.
    config.baseURL = '/api/v1/model-gateway'
    config.url = `/channels/${test[1]}/test`
    config.method = 'post'
    config.data = config.params ?? {}
    config.params = undefined
  }
  if (config.method === 'get' && discovery) {
    config.baseURL = '/api/v1/model-gateway'
    config.url = `/channels/${discovery[1]}/directory`
    config.method = 'post'
    config.data = {}
  }
  if (
    config.method === 'put' &&
    config.url?.replace(/\/$/, '') === '/api/channel'
  ) {
    const payload =
      typeof config.data === 'string' ? JSON.parse(config.data) : config.data
    const snapshot = channelSnapshots.get(payload?.id)
    if (
      snapshot &&
      typeof payload.models === 'string' &&
      Object.keys(payload).every((key) => ['id', 'models'].includes(key))
    ) {
      const current = (
        await api.get(`/channels/${payload.id}`, {
          baseURL: '/api/v1/model-gateway',
        })
      ).data.data
      if (current.models !== snapshot.models)
        throw new Error('渠道模型已变更，请关闭测试窗口后重新打开。')
      config.baseURL = '/api/v1/model-gateway'
      config.url = `/channels/${payload.id}/fields`
      config.method = 'patch'
      config.data = {
        models: payload.models.split(',').filter(Boolean),
        revision: current.revision,
      }
    } else {
      const revision = editorRevisions.get(payload?.id)
      if (!revision) throw new Error('请先重新打开渠道编辑页，再保存配置。')
      config.headers.set('If-Match', revision)
    }
  }
  if (config.method && config.method !== 'get' && config.method !== 'head')
    config.headers.set('x-csrf-token', csrf)
  return config
})
api.interceptors.response.use(
  (response) => {
    const detail = response.config.url?.match(/^\/api\/channel\/(\d+)$/)
    // Refetching a dirty native form must not silently advance its optimistic
    // lock. A new editor session clears this snapshot when it opens.
    if (
      detail &&
      !editorRevisions.has(Number(detail[1])) &&
      typeof response.data?.data?.revision === 'string'
    ) {
      editorRevisions.set(Number(detail[1]), response.data.data.revision)
    }
    if (
      response.config.baseURL === '/api/v1/model-gateway' &&
      /\/channels\/\d+\/directory$/.test(response.config.url ?? '')
    ) {
      response.data = { success: true, data: response.data.models }
    } else if (
      response.config.baseURL === '/api/v1/model-gateway' &&
      /\/channels\/\d+\/test$/.test(response.config.url ?? '')
    ) {
      response.data = { success: true, ...response.data.data }
    } else if (
      response.config.baseURL === '/api/v1/model-gateway' &&
      /\/channels\/\d+\/fields$/.test(response.config.url ?? '')
    ) {
      const channel = response.data.data
      bindNativeChannelSnapshot(channel)
      response.data = { success: true, data: channel }
    }
    return response
  },
  (error) => {
    const message = error?.response?.data?.error?.message
    if (typeof message === 'string')
      error.response.data = { success: false, message }
    return Promise.reject(error)
  }
)

// These flags belong to the upstream HTTP client. Actvero supplies the session
// and native forms never start a second login or refresh flow.
declare module 'axios' {
  interface AxiosRequestConfig {
    disableDuplicate?: boolean
    skipBusinessError?: boolean
    skipErrorHandler?: boolean
    skipAuthRefresh?: boolean
    acceptAuthRotation?: boolean
    singleUseAuthorization?: boolean
  }
}

export type RefreshOutcome =
  | { kind: 'anonymous' }
  | { kind: 'transient_error'; error: unknown }
  | { kind: 'authenticated'; bundle: AuthBundle }
  | { kind: 'out_of_sync'; code?: string }
export async function refreshAuthentication(): Promise<RefreshOutcome> {
  return { kind: 'out_of_sync', code: 'ACTVERO_SESSION_REQUIRED' }
}
export function isAuthBundle(value: unknown): value is AuthBundle {
  return (
    !!value &&
    typeof value === 'object' &&
    'user' in value &&
    'access_token' in value
  )
}
export async function getStatus() {
  return (
    await api.get<{ success: boolean; data: Record<string, unknown> }>(
      '/api/status'
    )
  ).data.data
}
export async function getNotice() {
  return (await api.get<{ success: boolean; data?: string }>('/api/notice'))
    .data
}
