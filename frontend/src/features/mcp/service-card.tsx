import { useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  RefreshCw,
  KeyRound,
  Pencil,
  Trash2,
  Wrench,
  Ellipsis,
  Copy,
  Link,
  History,
  Activity,
} from 'lucide-react'
import { toast } from 'sonner'
import { messageOf } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
  CollapsibleHeader,
} from '@/components/ui/collapsible'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuGroup,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { TokenEstimate } from './capability-controls'
import { useCapabilities, useTokenCounts, copyText } from './capability-data'
import { CapabilityPanel } from './capability-panel'
import { ConnectionDialog } from './connection-dialog'
import { ServiceIcon } from './presentation'
import { ServiceEditor } from './service-editor'
import {
  useDiscovery,
  useMcp,
  serviceInput,
  serviceName,
  type Service,
} from './shared'

export function ServiceCard({ service }: { service: Service }) {
  const { write, invalidate, discoverSaved } = useMcp()
  const discovery = useDiscovery(service.id)
  const connecting = discovery?.connecting ?? false
  const healthIsLatest =
    service.connection_options?.health_enabled &&
    service.enabled &&
    service.health_checked_at &&
    (!service.checked_at || service.health_checked_at > service.checked_at)
  const connectionError =
    discovery?.error || (healthIsLatest ? service.health_error : service.error)
  const catalog = useCapabilities(service.id)
  const tokenCounts = useTokenCounts(catalog.data?.items)
  const tools = catalog.data?.items.filter((c) => c.kind === 'tools')
  const selected = tools?.filter((c) => c.enabled)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const returnFocus = () => menuTrigger.current?.focus()
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('tools')
  const [edit, setEdit] = useState(false)
  const [credentials, setCredentials] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [pending, setPending] = useState(false)
  async function action(kind: 'discover' | 'toggle' | 'delete') {
    if (kind === 'discover') {
      void discoverSaved([service])
      return
    }
    setPending(true)
    try {
      if (kind === 'toggle') {
        await write('/services/' + service.id, 'PUT', {
          ...serviceInput(service),
          version: service.version,
          enabled: !service.enabled,
        })
      } else await write('/services/' + service.id, 'DELETE')
      await invalidate()
      setDeleting(false)
    } catch (e) {
      toast.error(messageOf(e))
      await invalidate()
    } finally {
      setPending(false)
    }
  }
  return (
    <>
      <Collapsible open={open} onOpenChange={setOpen}>
        <Card density='compact'>
          <CollapsibleHeader
            expandOnClick
            className='-my-2 py-2'
            data-state={open ? 'open' : 'closed'}
          >
            <CardHeader layout='row' className='overflow-x-auto'>
              <div className='flex w-full min-w-[40rem] items-center gap-4'>
                <div className='flex min-w-0 flex-1 items-center gap-3'>
                  <CollapsibleTrigger asChild>
                    <Button
                      variant='ghost'
                      size='icon'
                      aria-label={`${open ? '收起' : '展开'}服务 ${serviceName(service)}`}
                    >
                      {open ? <ChevronDown /> : <ChevronRight />}
                    </Button>
                  </CollapsibleTrigger>
                  <ServiceIcon
                    name={serviceName(service)}
                    icon={service.icon}
                    size='md'
                  />
                  <div className='flex h-10 min-w-0 flex-1 flex-col justify-center'>
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
                </div>
                <div className='flex shrink-0 items-center justify-end gap-4'>
                  <div className='flex items-center gap-2'>
                    <Badge
                      dot
                      role='status'
                      title={
                        connecting
                          ? undefined
                          : connectionError ||
                            (healthIsLatest
                              ? `最近检查：${new Date(service.health_checked_at!).toLocaleString()}`
                              : service.checked_at
                                ? `最近读取：${new Date(service.checked_at).toLocaleString()}`
                                : undefined)
                      }
                      variant={
                        connecting
                          ? 'secondary'
                          : connectionError
                            ? 'destructive'
                            : healthIsLatest || service.checked_at
                              ? 'success'
                              : 'secondary'
                      }
                    >
                      {connecting
                        ? '连接中'
                        : connectionError
                          ? '连接失败'
                          : healthIsLatest || service.checked_at
                            ? '已连接'
                            : service.configured
                              ? '未连接'
                              : '待配置凭据'}
                    </Badge>
                    <Button
                      variant='ghost'
                      size='sm'
                      aria-label={`展开工具 ${serviceName(service)}`}
                      onClick={() => {
                        setOpen(true)
                        setTab('tools')
                      }}
                    >
                      <Wrench />
                      {selected?.length ?? '…'}/
                      {tools?.length ?? service.counts.tools ?? 0}
                    </Button>
                  </div>
                  <TokenEstimate
                    count={
                      tokenCounts
                        ? (selected ?? []).reduce(
                            (n, c) => n + (tokenCounts[c.key] ?? 0),
                            0
                          )
                        : undefined
                    }
                    total={
                      tokenCounts
                        ? Object.values(tokenCounts).reduce((a, b) => a + b, 0)
                        : undefined
                    }
                  />
                  <div className='flex items-center gap-2'>
                    <Switch
                      aria-label={`启用服务 ${serviceName(service)}`}
                      checked={service.enabled}
                      disabled={pending || connecting}
                      onCheckedChange={() => void action('toggle')}
                    />
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          ref={menuTrigger}
                          variant='ghost'
                          size='icon'
                          aria-label={`更多服务操作 ${serviceName(service)}`}
                          disabled={pending || connecting}
                        >
                          <Ellipsis />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align='end'
                        onCloseAutoFocus={(event) => {
                          if (edit || credentials || deleting)
                            event.preventDefault()
                        }}
                      >
                        <DropdownMenuGroup>
                          <DropdownMenuItem onSelect={() => setEdit(true)}>
                            <Pencil />
                            编辑
                          </DropdownMenuItem>
                          {service.auth_mode !== 'none' && (
                            <DropdownMenuItem
                              onSelect={() => setCredentials(true)}
                            >
                              <KeyRound />
                              {service.auth_mode === 'organization'
                                ? '组织凭据'
                                : '我的测试凭据'}
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem
                            disabled={pending || !service.configured}
                            onSelect={() => void action('discover')}
                          >
                            <RefreshCw />
                            刷新工具
                          </DropdownMenuItem>
                          <DropdownMenuItem asChild>
                            <a href={`/mcp-calls?service=${service.id}`}>
                              <History />
                              查看调用记录
                            </a>
                          </DropdownMenuItem>
                          <DropdownMenuItem asChild>
                            <a href={`/mcp-logs?service=${service.id}`}>
                              <Activity />
                              查看连接日志
                            </a>
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={!service.url}
                            onSelect={() =>
                              void copyText(service.url, '上游地址')
                            }
                          >
                            <Link />
                            复制上游地址
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              void copyText(
                                JSON.stringify(
                                  {
                                    services: [
                                      {
                                        ...serviceInput(service),
                                        enabled: false,
                                      },
                                    ],
                                  },
                                  null,
                                  2
                                ),
                                '配置 JSON（不含凭据）'
                              )
                            }
                          >
                            <Copy />
                            复制配置 JSON
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                          <DropdownMenuItem
                            variant='destructive'
                            onSelect={() => setDeleting(true)}
                          >
                            <Trash2 />
                            删除服务
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </div>
            </CardHeader>
          </CollapsibleHeader>
          <CollapsibleContent>
            <Separator className='mt-2' />
            <CardContent tone='muted' className='py-4'>
              <CapabilityPanel service={service} tab={tab} onTab={setTab} />
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
      {edit && (
        <ServiceEditor
          service={service}
          close={() => setEdit(false)}
          returnFocus={returnFocus}
        />
      )}{' '}
      {credentials && (
        <ConnectionDialog
          service={service}
          close={() => setCredentials(false)}
          returnFocus={returnFocus}
        />
      )}
      <AlertDialog
        open={deleting}
        onOpenChange={(v) => {
          if (!pending) setDeleting(v)
        }}
      >
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            returnFocus()
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>删除 {service.name}？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除此服务的配置和已保存连接。上游服务不会被删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={pending || connecting}>
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={pending || connecting}
              onClick={(e) => {
                e.preventDefault()
                void action('delete')
              }}
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
