import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RequestError, LoadingState } from '@/components/request-state'
import { AuthLayout } from './auth-layout'
import { invitationToken } from './invitation-token'
import { JoinSetup } from './join-setup'
import { loginUrl, useSession } from './session'

export function JoinPage() {
  const { data: session, error: sessionError } = useSession()
  const client = useQueryClient()
  const claimStarted = useRef(false)
  const [token] = useState(() => invitationToken(window.location.hash))
  const [ready, setReady] = useState(!token)
  const [claimError, setClaimError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [claimEmail, setClaimEmail] = useState('')
  const [claimName, setClaimName] = useState('')
  useEffect(() => {
    if (claimStarted.current || !session) return
    claimStarted.current = true
    window.history.replaceState(null, '', '/join')
    if (!token) return
    api('/invitations/claim', 'POST', { token }, session.csrf)
      .then(() => setReady(true))
      .catch(setClaimError)
  }, [session, token])
  const preview = useQuery({
    queryKey: ['invitation', session?.user?.id],
    queryFn: () => api<Schema['InvitationPreview']>('/invitations/current'),
    enabled: ready,
    retry: false,
  })
  const accept = useMutation({
    mutationFn: () =>
      api('/invitations/accept', 'POST', undefined, session?.csrf),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['session'] })
      await preview.refetch()
    },
  })
  const claimDetails = useMutation({
    mutationFn: () =>
      api(
        '/invitations/claim',
        'POST',
        { token, email: claimEmail, name: claimName },
        session?.csrf
      ),
    onSuccess: async () => {
      await preview.refetch()
    },
  })
  const activate = useMutation({
    mutationFn: () =>
      api<Schema['Message']>(
        '/invitations/activate',
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: (value) => setNotice(value.message),
  })
  const invitation = preview.data
  const state = invitation?.state
  const organization = invitation?.tenant_name
  const activationRequired = invitation?.activation_required ?? false
  const errors: Record<string, string> = {
    expired: '邀请已过期或被撤销，请联系管理员获取新邀请。',
    mismatch: '当前登录账号与受邀账号不一致，请切换账号。',
    paused: '你的访问已暂停，请联系管理员。',
    unavailable: '组织暂不可用，请联系管理员。',
  }
  return (
    <AuthLayout
      variant='invitation'
      title={
        state === 'setup' && organization
          ? `设置账号并加入 ${organization}`
          : state === 'accepted'
            ? organization
              ? `已加入 ${organization}`
              : '已加入组织'
            : organization
              ? `加入 ${organization}`
              : '接受成员邀请'
      }
      description={
        state === 'setup'
          ? `受邀邮箱 ${invitation?.email_hint ?? ''}`
          : state === 'claim'
            ? '填写自己的账号信息，继续加入组织。'
            : state === 'login' && !activationRequired
              ? '请使用收到邀请邮件的账号登录。'
              : undefined
      }
    >
      {(sessionError ||
        claimError ||
        preview.error ||
        accept.error ||
        activate.error ||
        claimDetails.error) && (
        <RequestError
          error={
            sessionError ||
            claimError ||
            preview.error ||
            accept.error ||
            activate.error ||
            claimDetails.error
          }
        />
      )}
      {notice && (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      {!sessionError && !claimError && (!ready || preview.isPending) && (
        <LoadingState />
      )}
      {state && errors[state] && (
        <Alert>
          <AlertDescription>{errors[state]}</AlertDescription>
        </Alert>
      )}
      {state === 'claim' && (
        <form
          className='flex flex-col gap-4'
          onSubmit={(event) => {
            event.preventDefault()
            claimDetails.mutate()
          }}
        >
          <p className='text-sm text-muted-foreground'>
            这是组织管理员邀请。请填写你自己的邮箱和姓名，继续完成账号登录。
          </p>
          <label className='flex flex-col gap-2 text-sm font-medium'>
            姓名
            <Input
              value={claimName}
              onChange={(event) => setClaimName(event.target.value)}
              autoComplete='name'
              required
            />
          </label>
          <label className='flex flex-col gap-2 text-sm font-medium'>
            邮箱
            <Input
              type='email'
              value={claimEmail}
              onChange={(event) => setClaimEmail(event.target.value)}
              autoComplete='email'
              required
            />
          </label>
          <Button disabled={claimDetails.isPending} type='submit'>
            {claimDetails.isPending ? '正在准备账号…' : '继续'}
          </Button>
        </form>
      )}
      {state === 'setup' && invitation && session && (
        <JoinSetup
          invitation={invitation}
          csrf={session.csrf}
          refresh={() => void preview.refetch()}
        />
      )}
      {state === 'login' && activationRequired && !notice && (
        <>
          <p className='text-sm text-muted-foreground'>
            请先通过邮件验证邮箱或设置密码，完成后再登录。
          </p>
          <Button
            disabled={activate.isPending}
            onClick={() => activate.mutate()}
          >
            {activate.isPending ? '正在发送…' : '发送账号设置邮件'}
          </Button>
        </>
      )}
      {state === 'login' && (!activationRequired || notice) && (
        <>
          <Button asChild>
            <a href={loginUrl('/join', true)}>
              {notice ? '设置完成，继续登录' : '登录并继续'}
            </a>
          </Button>
          {notice && (
            <Button
              variant='link'
              disabled={activate.isPending}
              onClick={() => activate.mutate()}
            >
              {activate.isPending ? '正在发送…' : '重发设置邮件'}
            </Button>
          )}
        </>
      )}
      {state === 'mismatch' && (
        <Button asChild>
          <a href={loginUrl('/join', true)}>切换账号</a>
        </Button>
      )}
      {state === 'ready' && (
        <>
          <p className='text-sm'>受邀邮箱：{preview.data?.email}</p>
          <p className='text-sm text-muted-foreground'>
            加入角色：
            {preview.data?.role === 'administrator' ? '组织管理员' : '普通成员'}
            <br />
            有效期至：
            {preview.data?.expires_at && dateTime(preview.data.expires_at)}
          </p>
          <Button disabled={accept.isPending} onClick={() => accept.mutate()}>
            {accept.isPending ? '正在加入…' : '确认加入'}
          </Button>
        </>
      )}
      {state === 'accepted' && (
        <Button asChild>
          <Link to='/console'>进入工作空间</Link>
        </Button>
      )}
    </AuthLayout>
  )
}
