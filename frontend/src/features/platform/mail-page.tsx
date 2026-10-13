import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Mail } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { MailSettingsForm, MailTestForm } from './mail-settings-form'

export function PlatformMailPage() {
  const [testing, setTesting] = useState(false)
  const mail = useQuery({
    queryKey: ['platform', 'mail'],
    queryFn: () => api<Schema['MailSettingsView']>('/platform/mail'),
  })

  return (
    <PageShell title='邮件服务'>
      {mail.isPending && <LoadingState />}
      {mail.isError && (
        <RequestError error={mail.error} retry={() => void mail.refetch()} />
      )}
      {mail.data && (
        <Card className='w-full max-w-2xl'>
          <CardHeader>
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <CardTitle>SMTP 配置</CardTitle>
              <Badge variant={mail.data.enabled ? 'secondary' : 'outline'}>
                {mail.data.enabled ? '已启用' : '未启用'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className='flex flex-col gap-6'>
            <MailSettingsForm
              saved={mail.data}
              action={
                <Dialog open={testing} onOpenChange={setTesting}>
                  <DialogTrigger asChild>
                    <Button
                      type='button'
                      variant='outline'
                      disabled={!mail.data.enabled}
                    >
                      <Mail data-icon='inline-start' />
                      发送测试邮件
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>发送测试邮件</DialogTitle>
                      <DialogDescription>
                        使用已保存的配置发送，请在发送后检查收件箱。
                      </DialogDescription>
                    </DialogHeader>
                    <MailTestForm />
                  </DialogContent>
                </Dialog>
              }
            />
            <p className='text-sm text-muted-foreground'>
              用于邀请邮件。账号验证与密码重置使用身份服务的邮件配置。
            </p>
          </CardContent>
        </Card>
      )}
    </PageShell>
  )
}
