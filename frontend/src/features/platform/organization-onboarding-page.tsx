import { useEffect, useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { AccountCard } from '@/components/account-card'
import { LoadingState, RequestError } from '@/components/request-state'
import { AuthLayout } from '@/features/auth/auth-layout'
import { invitationToken } from '@/features/auth/invitation-token'
import { loginUrl, useSession } from '@/features/auth/session'
import { OpeningAccountForm } from './opening-account-form'

const schema = z.object({
  organization_name: z.string().trim().min(2, '组织名称至少 2 个字符').max(60),
})

export function OrganizationOnboardingPage({
  invitation = false,
}: {
  invitation?: boolean
}) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const path = invitation ? '/organization-invite' : '/organization-onboarding'
  const [token] = useState(() =>
    invitation ? invitationToken(window.location.hash) : ''
  )
  const [flow, setFlow] = useState(() =>
    token ? '' : (new URLSearchParams(window.location.search).get('flow') ?? '')
  )
  const [error, setError] = useState<unknown>(null)
  const [loginError] = useState(() =>
    new URLSearchParams(window.location.search).has('login_error')
  )
  const [retry, setRetry] = useState(0)
  const starting = useRef(false)
  useEffect(() => {
    if (flow || starting.current || !session) return
    starting.current = true
    api<Schema['OpeningFlowView']>(
      '/organization-onboarding/flows',
      'POST',
      { invitation, ...(token ? { token } : {}) },
      session.csrf
    )
      .then((result) => {
        window.history.replaceState(
          window.history.state,
          '',
          `${path}?flow=${result.flow_id}`
        )
        setFlow(result.flow_id)
      })
      .catch((failure) => {
        starting.current = false
        setError(failure)
      })
  }, [flow, invitation, path, retry, session, token])
  const query = useQuery({
    queryKey: ['organization-opening', flow, invitation, session?.user?.id],
    queryFn: () =>
      api<Schema['OpeningPreview']>(
        `/organization-onboarding/current?invitation=${invitation}&flow=${flow}`
      ),
    enabled: !!flow && !!session,
    retry: false,
    refetchInterval: 15000,
  })
  const preview = query.data
  // Render and submit the identity confirmed by this flow's response, not a stale global session.
  const account = preview?.account
  const login = loginUrl(path, true, flow)
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { organization_name: '' },
  })
  useEffect(() => {
    if (
      preview?.organization_name &&
      !form.getFieldState('organization_name').isDirty
    )
      form.setValue('organization_name', preview.organization_name)
  }, [form, preview?.organization_name])
  const submit = useMutation({
    mutationFn: (organization_name: string) =>
      api<Schema['OpeningPreview']>(
        `/organization-onboarding/submit?flow=${flow}`,
        'POST',
        { organization_name, invitation, confirmed_user_id: account?.id },
        session?.csrf
      ),
    onSuccess: async (result) => {
      client.setQueryData(
        ['organization-opening', flow, invitation, session?.user?.id],
        result
      )
      await client.invalidateQueries({ queryKey: ['session'] })
      await query.refetch()
    },
  })
  const verify = useMutation({
    mutationFn: async () => {
      await api(
        `/organization-onboarding/draft?flow=${flow}`,
        'PUT',
        { organization_name: form.getValues('organization_name') },
        session?.csrf
      )
      return api(
        `/organization-onboarding/verify-email?invitation=${invitation}&flow=${flow}`,
        'POST',
        undefined,
        session?.csrf
      )
    },
    onSuccess: () => toast.success('验证邮件已发送，请验证后返回继续'),
  })
  const checkEmail = useMutation({
    mutationFn: () =>
      api(
        `/organization-onboarding/check-email?invitation=${invitation}&flow=${flow}`,
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: () => query.refetch(),
  })
  const switchAccount = useMutation({
    mutationFn: () =>
      api(
        `/organization-onboarding/draft?flow=${flow}`,
        'PUT',
        { organization_name: form.getValues('organization_name') },
        session?.csrf
      ),
    onSuccess: () => window.location.assign(login),
  })
  const restart = useMutation({
    mutationFn: () =>
      api(
        `/organization-onboarding/restart?flow=${flow}`,
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: () => query.refetch(),
  })
  const enter = useMutation({
    mutationFn: () =>
      api(
        '/auth/workspace',
        'POST',
        { tenant_id: preview?.organization_id },
        session?.csrf
      ),
    onSuccess: () => window.location.assign('/'),
  })
  const title =
    preview?.state === 'pending'
      ? '申请已提交'
      : preview?.state === 'rejected'
        ? '申请未通过'
        : ['approved', 'completed'].includes(preview?.state ?? '')
          ? '组织已开通'
          : preview?.mode === 'approval'
            ? '申请开通组织'
            : '开通组织'
  const failure =
    error ||
    query.error ||
    submit.error ||
    verify.error ||
    checkEmail.error ||
    restart.error ||
    enter.error ||
    switchAccount.error
  async function refresh() {
    setError(null)
    submit.reset()
    verify.reset()
    checkEmail.reset()
    switchAccount.reset()
    restart.reset()
    enter.reset()
    if (!flow) setRetry((value) => value + 1)
    await client.invalidateQueries({ queryKey: ['session'] })
    if (flow) await query.refetch()
  }
  return (
    <AuthLayout title={title} description=''>
      {failure ? (
        <RequestError error={failure} retry={() => void refresh()} />
      ) : null}
      {!error && (!flow || query.isPending) && <LoadingState />}
      {loginError && preview?.state === 'form' && (
        <Alert>
          <AlertDescription>
            登录未完成，请确认当前账号后继续，或重新登录。
          </AlertDescription>
        </Alert>
      )}
      {preview?.state === 'form' && !account && session && (
        <OpeningAccountForm
          invitation={invitation}
          flow={flow}
          csrf={session.csrf}
          recipient={preview.recipient_email}
          login={login}
        />
      )}
      {account && ['form', 'mismatch'].includes(preview?.state ?? '') && (
        <div className='flex flex-col gap-2'>
          <p className='text-sm font-medium'>管理员账号</p>
          <AccountCard user={account} wrapDetails />
          <Button
            variant='link'
            className='self-end'
            disabled={switchAccount.isPending || submit.isPending}
            onClick={() => switchAccount.mutate()}
          >
            使用其他账号
          </Button>
        </div>
      )}
      {preview?.state === 'form' && account && (
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit((values) =>
              submit.mutate(values.organization_name)
            )}
          >
            <FormField
              control={form.control}
              name='organization_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>组织名称</FormLabel>
                  <FormControl>
                    <Input autoComplete='organization' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {preview.verify_email && (
              <Alert>
                <AlertDescription>
                  <span>开通前需要验证邮箱。</span>
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      type='button'
                      variant='link'
                      disabled={verify.isPending}
                      onClick={() => verify.mutate()}
                    >
                      发送验证邮件
                    </Button>
                    <Button
                      type='button'
                      variant='link'
                      disabled={checkEmail.isPending}
                      onClick={() => checkEmail.mutate()}
                    >
                      我已验证，继续
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
            <Button
              disabled={
                submit.isPending ||
                switchAccount.isPending ||
                preview.verify_email
              }
            >
              {submit.isPending
                ? '处理中…'
                : preview.mode === 'approval'
                  ? '提交申请'
                  : '开通组织'}
            </Button>
          </form>
        </Form>
      )}
      {preview?.state === 'pending' && (
        <>
          <p>正在等待平台审核，你可以稍后返回查看结果。</p>
          <Button variant='outline' asChild>
            <a href='/'>返回平台</a>
          </Button>
        </>
      )}
      {preview?.state === 'rejected' && (
        <>
          <Alert>
            <AlertDescription>{preview.reason}</AlertDescription>
          </Alert>
          <Button onClick={() => restart.mutate()} disabled={restart.isPending}>
            重新申请
          </Button>
        </>
      )}
      {['approved', 'completed'].includes(preview?.state ?? '') && (
        <>
          <p>{preview?.organization_name}</p>
          <Button onClick={() => enter.mutate()} disabled={enter.isPending}>
            进入组织
          </Button>
        </>
      )}
      {preview?.state === 'mismatch' && (
        <Alert>
          <AlertDescription>
            {preview.recipient_email
              ? `请使用受邀邮箱 ${preview.recipient_email} 对应的账号登录。`
              : '请使用刚创建的管理员账号登录。'}
          </AlertDescription>
        </Alert>
      )}
      {preview?.state === 'login' && (
        <>
          <p>请登录原账号继续开通。</p>
          <Button asChild>
            <a href={login}>登录并继续</a>
          </Button>
        </>
      )}
      {['closed', 'expired', 'used'].includes(preview?.state ?? '') && (
        <>
          <Alert>
            <AlertDescription>
              {preview?.state === 'closed'
                ? '当前仅接受邀请开通，请联系平台运营人员。'
                : preview?.state === 'used'
                  ? '此邀请已被使用。'
                  : '此邀请已过期或被撤销。'}
            </AlertDescription>
          </Alert>
          <Button asChild variant='outline'>
            <a href='/'>返回平台</a>
          </Button>
        </>
      )}
    </AuthLayout>
  )
}
