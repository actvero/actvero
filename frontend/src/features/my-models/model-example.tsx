import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { memberOperations } from './search'

type Operation = Schema['MemberOperationView']

function shellQuote(value: string) {
  return `'${value.split("'").join("'\"'\"'")}'`
}

export function ModelExample({
  model,
  operation,
  close,
  restoreFocus,
}: {
  model: Schema['MemberModelView']
  operation: Operation
  close: () => void
  restoreFocus: () => void
}) {
  const [copying, setCopying] = useState(false)
  const endpoint = operation.endpoint
  const requestBody = JSON.stringify(endpoint.example, null, 2)
  const url = `${window.location.origin}${endpoint.path}`
  const command =
    operation.kind === 'transcription'
      ? [
          `curl --request ${endpoint.method} ${shellQuote(url)} \\`,
          '  --header "Authorization: Bearer ${ACTVERO_API_KEY}" \\',
          `  --form ${shellQuote(`model=${model.slug}`)} \\`,
          "  --form 'file=@sample.wav;type=audio/wav'",
        ].join('\n')
      : [
          `curl --request ${endpoint.method} ${shellQuote(url)} \\`,
          '  --header "Authorization: Bearer ${ACTVERO_API_KEY}" \\',
          "  --header 'Content-Type: application/json' \\",
          `  --data ${shellQuote(requestBody)}${operation.kind === 'speech' ? ' \\\n  --output speech.wav' : ''}`,
        ].join('\n')

  async function copy(value: string, what: string) {
    setCopying(true)
    try {
      await navigator.clipboard.writeText(value)
      toast.success(`已复制${what}`)
    } catch {
      toast.error('复制失败，请选择文本后手动复制')
    } finally {
      setCopying(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        className='flex max-h-[min(90dvh,48rem)] min-w-0 flex-col sm:max-w-2xl'
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocus()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            接入示例 · {model.name} · {memberOperations[operation.kind]}
          </DialogTitle>
          <DialogDescription>
            此模板只包含平台公开接口与模型名称。实际请求还需你自己的访问密钥、当前权限和额度；页面不会发送推理请求。
          </DialogDescription>
        </DialogHeader>
        <div className='flex min-h-0 min-w-0 flex-col gap-3 overflow-y-auto'>
          <p className='text-sm break-all'>
            客户端接口：{endpoint.method} {endpoint.path}
          </p>
          <p className='text-sm break-all'>公开模型 ID：{model.slug}</p>
          {operation.kind === 'chat' && (
            <p className='text-sm text-muted-foreground'>
              流式：
              {endpoint.stream &&
              operation.capabilities.streaming === 'supported'
                ? '模型已声明支持'
                : '模型支持未确认或未开放'}{' '}
              · 工具：
              {endpoint.tools && operation.capabilities.tools === 'supported'
                ? '模型已声明支持'
                : '模型支持未确认或未开放'}
              ；实际调用仍由服务端校验。
            </p>
          )}
          <Textarea
            aria-label={`${memberOperations[operation.kind]}接入命令`}
            readOnly
            value={command}
            rows={10}
            className='min-h-40 min-w-0 font-mono text-xs'
          />
          <p className='text-xs text-muted-foreground'>
            示例中的 ACTVERO_API_KEY
            是本机环境变量占位；不要把真实密钥贴入本页面。
          </p>
        </div>
        <DialogFooter className='flex-wrap sm:justify-between'>
          <Button asChild variant='outline'>
            <Link to='/my-access-keys'>前往访问密钥</Link>
          </Button>
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              disabled={copying}
              onClick={() =>
                void copy(`${endpoint.method} ${endpoint.path}`, '端点')
              }
            >
              <Copy />
              复制端点
            </Button>
            <Button
              type='button'
              variant='outline'
              disabled={copying}
              onClick={() => void copy(command, '示例模板')}
            >
              <Copy />
              复制示例
            </Button>
            <Button type='button' onClick={close}>
              关闭
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
