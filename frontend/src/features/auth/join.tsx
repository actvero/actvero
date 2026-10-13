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
import { loginUrl, useSession } from './session'

export function JoinPage() {
  const { data: session } = useSession()
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
  const state = preview.data?.state
  const errors: Record<string, string> = {
    expired: '邀请已过期或被撤销，请联系管理员获取新邀请。',
    mismatch: '当前登录账号与受邀账号不一致，请切换账号。',
    paused: '你的访问已暂停，请联系管理员。',
    unavailable: '组织暂不可用，请联系管理员。',
  }
  return (
    <AuthLayout
      title={
        state === 'ready'
          ? '加入 ' + preview.data?.tenant_name
          : state === 'accepted'
            ? '已加入组织'
            : '接受成员邀请'
      }
      description={
        state === 'claim'
          ? '填写自己的账号信息，继续加入组织。'
          : '验证你的账号后，确认加入组织。'
      }
    >
      {(claimError ||
        preview.error ||
        accept.error ||
        activate.error ||
        claimDetails.error) && (
        <RequestError
          error={
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
      {!claimError && (!ready || preview.isPending) && <LoadingState />}
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
      {state === 'login' && (
        <>
          {preview.data?.activation_required && (
            <Button
              variant='outline'
              disabled={activate.isPending}
              onClick={() => activate.mutate()}
            >
              {activate.isPending ? '正在发送…' : '发送账号激活邮件'}
            </Button>
          )}
          <Button asChild>
            <a href={loginUrl('/join', true)}>登录受邀账号</a>
          </Button>
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
