import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { LoadingState, RequestError } from '@/components/request-state'
import { AuthLayout } from './auth-layout'
import { loginUrl, useSession } from './session'

export function CliAuthorizePage() {
  const session = useSession()
  const [proof] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    return {
      attempt_id: params.get('attempt_id') ?? '',
      state: params.get('state') ?? '',
    }
  })
  const valid =
    /^[\da-f-]{36}$/i.test(proof.attempt_id) &&
    /^[\w-]{43,100}$/.test(proof.state)
  return (
    <AuthLayout
      title='授权 CLI 接入'
      description='选择允许这台设备访问的组织和权限。'
    >
      {!valid ? (
        <p role='alert'>授权链接无效，请返回 CLI 重新发起。</p>
      ) : session.isError ? (
        <RequestError
          error={session.error}
          retry={() => void session.refetch()}
        />
      ) : !session.data ? (
        <LoadingState />
      ) : !session.data.authenticated ? (
        <>
          <p className='text-sm text-muted-foreground'>
            请先登录，再确认此次 CLI 接入。登录本身不会授予管理权限。
          </p>
          <Button asChild>
            <a href={loginUrl(window.location.pathname + window.location.hash)}>
              登录并继续
            </a>
          </Button>
        </>
      ) : (
        <>
          <CliConsentForm
            key={session.data.user?.id}
            proof={proof}
            csrf={session.data.csrf}
          />
          <Button asChild variant='link'>
            <a
              href={loginUrl(
                window.location.pathname + window.location.hash,
                true
              )}
            >
              切换登录账号
            </a>
          </Button>
        </>
      )}
    </AuthLayout>
  )
}

export function CliConsentForm({
  proof,
  csrf,
  navigate = (url: string) => window.location.assign(url),
}: {
  proof: Schema['CliConsentProof']
  csrf: string
  navigate?: (url: string) => void
}) {
  const [orgIds, setOrgIds] = useState<string[]>([])
  const [write, setWrite] = useState(false)
  const [finished, setFinished] = useState(false)
  const context = useQuery({
    queryKey: ['cli-authorization', proof, csrf],
    queryFn: () =>
      api<Schema['CliConsentView']>(
        '/cli-authorization/context',
        'POST',
        proof,
        csrf
      ),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const decision = useMutation({
    mutationFn: (approve: boolean) =>
      api<Schema['CliConsentResult']>(
        '/cli-authorization/decision',
        'POST',
        {
          ...proof,
          approve,
          org_ids: approve ? orgIds : [],
          scope: write ? 'management:read management:write' : 'management:read',
        } satisfies Schema['CliConsentDecision'],
        csrf
      ),
    onSuccess: (result) => {
      setFinished(true)
      navigate(result.redirect_url)
    },
  })
  if (context.isPending) return <LoadingState />
  if (context.isError)
    return (
      <RequestError
        error={context.error}
        retry={() => void context.refetch()}
      />
    )
  const disabled = decision.isPending || finished
  return (
    <>
      <dl className='space-y-2 text-sm'>
        <div>
          <dt className='text-muted-foreground'>登录账号</dt>
          <dd>
            {context.data.user.name} · {context.data.user.email}
          </dd>
        </div>
        <div>
          <dt className='text-muted-foreground'>申请设备</dt>
          <dd className='break-words'>{context.data.device_name}</dd>
        </div>
      </dl>
      <p className='text-sm text-muted-foreground'>
        仅在你刚刚从自己的终端或 Agent 发起接入时继续。
      </p>
      <fieldset className='space-y-3' disabled={disabled}>
        <legend className='mb-2 text-sm font-medium'>允许访问的组织</legend>
        {context.data.organizations.length ? (
          context.data.organizations.map((org) => (
            <label key={org.org_id} className='flex items-start gap-2 text-sm'>
              <input
                type='checkbox'
                className='mt-1 accent-primary'
                checked={orgIds.includes(org.org_id)}
                onChange={(event) =>
                  setOrgIds(
                    event.target.checked
                      ? [...orgIds, org.org_id]
                      : orgIds.filter((id) => id !== org.org_id)
                  )
                }
              />
              <span>
                {org.name}
                <span className='block text-xs break-all text-muted-foreground'>
                  {org.org_id}
                </span>
              </span>
            </label>
          ))
        ) : (
          <p className='text-sm text-muted-foreground'>
            当前账号没有可管理的组织，请联系组织管理员。
          </p>
        )}
      </fieldset>
      <fieldset className='space-y-3' disabled={disabled}>
        <legend className='mb-2 text-sm font-medium'>授予这台设备的权限</legend>
        <label className='flex items-start gap-2 text-sm'>
          <input
            type='radio'
            name='cli-permission'
            className='mt-1 accent-primary'
            checked={!write}
            onChange={() => setWrite(false)}
          />
          <span>
            只读查询
            <span className='block text-muted-foreground'>
              查看渠道、Skills、MCP 与专家。
            </span>
          </span>
        </label>
        <label className='flex items-start gap-2 text-sm'>
          <input
            type='radio'
            name='cli-permission'
            className='mt-1 accent-primary'
            checked={write}
            onChange={() => setWrite(true)}
          />
          <span>
            管理资源
            <span className='block text-muted-foreground'>
              包括新建、修改、发布、删除 Skills、MCP 与专家，以及执行 MCP 测试。
            </span>
          </span>
        </label>
      </fieldset>
      <p className='text-sm text-muted-foreground'>
        每次操作仍受你在组织内的当前权限约束。此授权不会自动执行资源操作。
      </p>
      {decision.isError && <RequestError error={decision.error} />}
      <div className='flex gap-3'>
        <Button
          disabled={disabled || !orgIds.length}
          onClick={() => decision.mutate(true)}
        >
          {disabled ? '正在返回 CLI…' : '确认授权'}
        </Button>
        <Button
          variant='outline'
          disabled={disabled}
          onClick={() => decision.mutate(false)}
        >
          拒绝
        </Button>
      </div>
    </>
  )
}
