import { useId, useState } from 'react'
import { toast } from 'sonner'
import { messageOf, type Schema } from '@/lib/api'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { applicationSettings, type Application } from './data'

const capabilities = [
  ['models_enabled', '模型', '发现并调用组织内所有已开放的模型。'],
  ['mcp_enabled', 'MCP', '同步组织 MCP 服务，调用已开放的工具、提示词和资源。'],
  ['skills_enabled', 'Skills', '同步组织已发布的技能，查看文件并下载技能包。'],
  ['experts_enabled', '专家', '同步组织已发布的专家，读取配置并检查依赖。'],
  [
    'knowledge_enabled',
    '知识库',
    '创建和管理应用自己的知识库，检索组织共享资料。',
  ],
] as const

export function ApplicationPermissions({
  app,
  save,
}: {
  app: Application
  save: (input: Schema['ApplicationUpdate']) => Promise<void>
}) {
  const root = useId()
  const [busy, setBusy] = useState(false)

  async function change(
    field: (typeof capabilities)[number][0],
    enabled: boolean
  ) {
    setBusy(true)
    try {
      await save({
        ...applicationSettings(app),
        [field]: enabled,
      })
      toast.success('权限已更新')
    } catch (error) {
      toast.error(messageOf(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className='max-w-3xl rounded-xl border'>
      {capabilities.map(([field, name, description], i) => {
        const id = root + field
        return (
          <div key={field}>
            {i > 0 && <Separator />}
            <div className='flex items-center justify-between gap-4 p-4'>
              <div className='flex flex-col gap-1'>
                <Label htmlFor={id}>{name}</Label>
                <p
                  id={id + '-description'}
                  className='text-sm text-muted-foreground'
                >
                  {description}
                </p>
              </div>
              <Switch
                id={id}
                aria-describedby={id + '-description'}
                checked={app[field]}
                disabled={busy}
                onCheckedChange={(checked) => void change(field, checked)}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
