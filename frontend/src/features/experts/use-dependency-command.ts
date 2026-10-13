import { useEffect, useRef, useState } from 'react'
import { z } from 'zod'
import { api, ApiError, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

const exact = z
  .object({
    key: z.string().min(1).max(80),
    from_version_id: z.string().uuid(),
    from_sha256: z.string().regex(/^[0-9a-f]{64}$/),
    to_version_id: z.string().uuid(),
    to_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  })
  .strict()
const selection = z
  .object({
    expert_id: z.string().uuid(),
    revision: z.number().int().positive(),
    changes: z.array(exact).min(1).max(32),
  })
  .strict()
const base = {
  resource_id: z.string().uuid(),
  request_id: z.string().uuid(),
  revision: z.number().int().positive(),
}
const commandSchema = z.discriminatedUnion('kind', [
  z
    .object({
      ...base,
      kind: z.literal('skill.publish'),
      version_id: z.string().uuid(),
      draft_updates: z.array(selection).max(50),
    })
    .strict(),
  z
    .object({
      ...base,
      kind: z.literal('expert.refresh_skills'),
      changes: z.array(exact).min(1).max(32),
    })
    .strict(),
])
type Command = z.infer<typeof commandSchema>
export type CommandInput =
  | Omit<
      Extract<Command, { kind: 'skill.publish' }>,
      'request_id' | 'resource_id'
    >
  | Omit<
      Extract<Command, { kind: 'expert.refresh_skills' }>,
      'request_id' | 'resource_id'
    >
function read(
  key: string,
  resourceId: string,
  kind: Command['kind']
): Command | undefined {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw || raw.length > 2_000_000) return undefined
    const parsed = commandSchema.safeParse(JSON.parse(raw))
    return parsed.success &&
      parsed.data.resource_id === resourceId &&
      parsed.data.kind === kind
      ? parsed.data
      : undefined
  } catch {
    return undefined
  }
}

/** Stores only IDs, revisions and digests, never expert instructions or credentials. */
export function useDependencyCommand(
  resourceId: string,
  kind: Command['kind'],
  onCommitted: (isLive: () => boolean) => Promise<void>
) {
  const { organization, user, csrf } = useOrganization()
  const storageKey = `dependency-command:${organization.tenant_id}:${user.id}:${kind}:${resourceId}`
  const [pending, setPending] = useState(() =>
    read(storageKey, resourceId, kind)
  )
  const [busy, setBusy] = useState(false)
  const [forbidden, setForbidden] = useState(false)
  const [error, setError] = useState<unknown>()
  const live = useRef(true)
  const epoch = useRef(0)
  const locked = useRef(false)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
      epoch.current += 1
    }
  }, [storageKey])
  function clear() {
    sessionStorage.removeItem(storageKey)
    setPending(undefined)
  }
  async function finish(isLive: () => boolean) {
    // Keep the receipt recoverable if refresh fails or storage cannot be cleared.
    await onCommitted(isLive)
    if (isLive()) clear()
  }
  function fail(e: unknown, definitive: boolean) {
    if (!live.current) return
    if (e instanceof ApiError && [401, 403].includes(e.status)) {
      setForbidden(true)
    } else if (
      definitive &&
      e instanceof ApiError &&
      [400, 404, 409, 422].includes(e.status)
    ) {
      try {
        clear()
      } catch {
        setError(new Error('无法清理更新编号，请按原编号查询回执'))
        return
      }
    }
    setError(e)
  }
  async function send(command: Command) {
    if (locked.current || forbidden) return
    locked.current = true
    const turn = epoch.current
    const isLive = () => live.current && epoch.current === turn
    let committed = false
    setBusy(true)
    setError(undefined)
    try {
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(command))
      } catch {
        throw new Error('浏览器无法保存更新编号；未发送更新，请检查存储后重试')
      }
      setPending(command)
      if (command.kind === 'skill.publish') {
        const { resource_id, kind: _kind, version_id, ...body } = command
        await api(
          `/skills/${resource_id}/versions/${version_id}/actions`,
          'POST',
          { ...body, action: 'publish' },
          csrf
        )
      } else {
        const { resource_id, kind: _kind, ...body } = command
        await api(`/experts/${resource_id}/refresh-skills`, 'POST', body, csrf)
      }
      committed = true
      if (isLive()) await finish(isLive)
    } catch (e) {
      if (isLive()) fail(e, !committed)
    } finally {
      locked.current = false
      if (isLive()) setBusy(false)
    }
  }
  return {
    pending,
    resetError: () => setError(undefined),
    reportError: (e: unknown) => fail(e, false),
    busy,
    forbidden,
    error,
    execute: async (input: CommandInput) => {
      if (pending || locked.current || forbidden) return
      let command: Command
      try {
        command = commandSchema.parse({
          ...input,
          resource_id: resourceId,
          request_id: crypto.randomUUID(),
        })
      } catch {
        setError(new Error('无法保存更新编号，请检查浏览器存储后重试'))
        return
      }
      await send(command)
    },
    replay: async () => {
      if (pending) await send(pending)
    },
    recover: async () => {
      if (!pending || locked.current || forbidden) return
      locked.current = true
      const turn = epoch.current
      const isLive = () => live.current && epoch.current === turn
      setBusy(true)
      setError(undefined)
      try {
        const result = await api<Schema['DependencyCommandView']>(
          `/experts/dependency-commands/${pending.request_id}`
        )
        if (result.resource_id !== resourceId || result.action !== kind)
          throw new Error('更新回执与原请求不一致')
        if (isLive()) await finish(isLive)
      } catch (e) {
        if (isLive())
          fail(
            e instanceof ApiError && e.status === 404
              ? new Error(
                  '尚无回执，原请求可能仍在完成。可稍后查询或按原编号重试。'
                )
              : e,
            false
          )
      } finally {
        locked.current = false
        if (isLive()) setBusy(false)
      }
    },
  }
}
