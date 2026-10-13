import { useRef, useState } from 'react'
import { KeyRound, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { RequestError } from '@/components/request-state'
import { ConnectionDialog } from './connection-dialog'
import { ServiceIcon } from './presentation'
import { serviceName, useDiscovery, useMcp, type Service } from './shared'

export function MemberServiceCard({ service }: { service: Service }) {
  const { discoverSaved } = useMcp()
  const discovery = useDiscovery(service.id)
  const [credentials, setCredentials] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const connecting = discovery?.connecting ?? false
  const error = discovery?.error || service.error
  const configured = service.configured
  const personal =
    service.auth_mode === 'personal' || service.auth_mode === 'oauth'
  const connected = Boolean(!connecting && !error && service.checked_at)
  const status =
    service.auth_mode === 'none'
      ? '无需配置'
      : connecting
        ? '连接中'
        : error
          ? '连接失败'
          : connected
            ? '已连接'
            : configured
              ? '待验证'
              : service.auth_mode === 'organization'
                ? '待管理员配置'
                : '待配置凭据'

  return (
    <>
      <Card density='compact'>
        <CardHeader layout='row' className='overflow-x-auto'>
          <div className='flex w-full min-w-[28rem] items-center gap-3'>
            <ServiceIcon
              name={serviceName(service)}
              icon={service.icon}
              size='md'
            />
            <div className='flex min-w-0 flex-1 flex-col justify-center'>
              <CardTitle
                size='body'
                className='truncate'
                title={serviceName(service)}
              >
                {serviceName(service)}
              </CardTitle>
              {service.description && (
                <CardDescription
                  className='truncate'
                  title={service.description}
                >
                  {service.description}
                </CardDescription>
              )}
            </div>
            <div className='flex shrink-0 items-center gap-3'>
              <Badge
                dot
                role='status'
                variant={
                  connecting
                    ? 'secondary'
                    : error
                      ? 'destructive'
                      : connected
                        ? 'success'
                        : 'secondary'
                }
              >
                {status}
              </Badge>
              <span className='text-sm text-muted-foreground'>
                工具 {service.counts.tools ?? 0}
              </span>
              {personal ? (
                <Button
                  ref={button}
                  variant='outline'
                  size='sm'
                  disabled={connecting}
                  onClick={() => setCredentials(true)}
                >
                  <KeyRound data-icon='inline-start' />
                  {configured ? '更新个人凭据' : '配置个人凭据'}
                </Button>
              ) : null}
              {configured && personal && !error && !connected && (
                <Button
                  variant='ghost'
                  size='sm'
                  disabled={connecting}
                  onClick={() =>
                    void discoverSaved([{ ...service, configured: true }])
                  }
                >
                  <RefreshCw data-icon='inline-start' />
                  验证连接
                </Button>
              )}
              {configured && personal && error && (
                <Button
                  variant='ghost'
                  size='sm'
                  disabled={connecting}
                  onClick={() =>
                    void discoverSaved([{ ...service, configured: true }])
                  }
                >
                  <RefreshCw data-icon='inline-start' />
                  重试
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
      </Card>
      {error && <RequestError error={new Error(error)} />}
      {credentials && (
        <ConnectionDialog
          service={service}
          memberMode
          close={() => setCredentials(false)}
          returnFocus={() => button.current?.focus()}
        />
      )}
    </>
  )
}
