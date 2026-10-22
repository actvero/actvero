import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Save, Terminal } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { CLI_VERSION, cliOnboardingPrompt } from './cli-onboarding'

type CliSettings = Schema['CliSettingsView']
const queryKey = ['platform', 'cli'] as const

export function PlatformCliSettingsPage() {
  const settings = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      api<CliSettings>('/platform/cli', 'GET', undefined, undefined, signal),
  })
  return (
    <PageShell
      title='CLI 接入'
      description='让终端和 Agent 管理平台上的 Skills、MCP 与专家。'
    >
      {settings.isPending && <LoadingState />}
      {settings.isError && (
        <RequestError
          error={settings.error}
          retry={() => void settings.refetch()}
        />
      )}
      {!settings.isError && settings.data && (
        <CliSettingsForm saved={settings.data} />
      )}
    </PageShell>
  )
}

function CliSettingsForm({ saved }: { saved: CliSettings }) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const [draft, setDraft] = useState<boolean | null>(null)
  const [write, setWrite] = useState(false)
  const enabled = draft ?? saved.enabled
  const prompt = cliOnboardingPrompt(saved.server_url, write)
  const update = useMutation({
    mutationFn: () =>
      api<CliSettings>('/platform/cli', 'PUT', { enabled }, session?.csrf),
    onSuccess: (value) => {
      client.setQueryData(queryKey, value)
      setDraft(null)
      toast.success('CLI 接入设置已保存')
    },
  })
  const forbidden =
    update.error instanceof ApiError && [401, 403].includes(update.error.status)
  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt)
      toast.success('已复制，可粘贴给 Agent')
    } catch {
      toast.error('无法访问剪贴板，请选中下方指令手动复制')
    }
  }
  return (
    <div className='grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]'>
      <div className='flex min-w-0 flex-col gap-6'>
        <Card>
          <CardHeader className='flex flex-row items-center justify-between gap-3'>
            <CardTitle>管理接口</CardTitle>
            <Badge variant={saved.enabled ? 'default' : 'secondary'}>
              {saved.enabled ? '已开启' : '已关闭'}
            </Badge>
          </CardHeader>
          <CardContent className='space-y-5'>
            <div className='flex items-center justify-between gap-4'>
              <div className='space-y-2'>
                <Label htmlFor='cli-enabled'>开启 CLI 接入</Label>
                <p className='text-sm text-muted-foreground'>
                  保存后立即生效。关闭后拒绝新的 CLI
                  请求，已发出的操作无法撤回。
                </p>
              </div>
              <Switch
                id='cli-enabled'
                checked={enabled}
                onCheckedChange={setDraft}
                disabled={update.isPending || forbidden}
              />
            </div>
            <p className='text-sm text-muted-foreground'>
              {saved.source === 'environment'
                ? '当前沿用部署配置，首次保存后以本页设置为准。'
                : '当前使用本页保存的设置，重启服务后仍然保留。'}
            </p>
            {update.isError && <RequestError error={update.error} />}
          </CardContent>
          <CardFooter>
            <Button
              onClick={() => update.mutate()}
              disabled={
                update.isPending || forbidden || enabled === saved.enabled
              }
            >
              <Save data-icon='inline-start' />
              {update.isPending ? '保存中…' : '保存设置'}
            </Button>
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>平台与登录</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4 text-sm'>
            <div>
              <p className='mb-1 text-muted-foreground'>平台地址</p>
              <p className='break-all'>{saved.server_url}</p>
            </div>
            <p>
              开启接口后，需要通过一次浏览器登录完成接入。登录服务尚未配置时，仅开启此开关仍无法登录。
            </p>
            <details>
              <summary className='cursor-pointer font-medium'>
                登录服务配置说明
              </summary>
              <div className='mt-3 space-y-3 text-muted-foreground'>
                <p className='break-all'>身份服务：{saved.issuer}</p>
                <p className='break-all'>公共客户端：{saved.client_id}</p>
                <p>
                  使用独立公共客户端、PKCE S256
                  和本机回环回调。已有身份库需单独配置；此页面不会修改身份服务。
                </p>
                <a
                  className='underline underline-offset-4'
                  href='https://github.com/actvero/actvero/blob/main/docs/CLI.md'
                  target='_blank'
                  rel='noreferrer'
                >
                  查看 CLI 接入文档
                </a>
              </div>
            </details>
          </CardContent>
        </Card>
      </div>
      <Card className='min-w-0'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Terminal className='size-5' />
            交给 Agent 配置
          </CardTitle>
        </CardHeader>
        <CardContent className='space-y-5'>
          <p className='text-sm text-muted-foreground'>
            复制指令到 Codex、Claude Code 等 Agent。它会安装
            CLI、检查平台连接并引导你登录。当前使用开发预览版 {CLI_VERSION}
            ，需要 Node.js 24 或以上版本。
          </p>
          <fieldset className='flex flex-wrap gap-4'>
            <legend className='mb-2 text-sm font-medium'>接入权限</legend>
            <label className='flex items-center gap-2 text-sm'>
              <input
                type='radio'
                name='cli-scope'
                checked={!write}
                onChange={() => setWrite(false)}
                className='accent-primary'
              />
              只读查询
            </label>
            <label className='flex items-center gap-2 text-sm'>
              <input
                type='radio'
                name='cli-scope'
                checked={write}
                onChange={() => setWrite(true)}
                className='accent-primary'
              />
              读写管理
            </label>
          </fieldset>
          <p className='text-sm text-muted-foreground'>
            读写管理仍受当前组织权限约束，资源维护需要组织管理员资格。
          </p>
          {!saved.enabled && (
            <p role='status' className='text-sm'>
              请先开启并保存 CLI 接入，再复制指令。
            </p>
          )}
          <Button
            onClick={() => void copy()}
            disabled={!saved.enabled || update.isPending || forbidden}
          >
            <Copy data-icon='inline-start' />
            复制给 Agent
          </Button>
          <div className='space-y-2'>
            <Label htmlFor='cli-agent-prompt'>接入指令预览</Label>
            <Textarea
              id='cli-agent-prompt'
              value={prompt}
              readOnly
              className='min-h-80 resize-y text-sm'
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
