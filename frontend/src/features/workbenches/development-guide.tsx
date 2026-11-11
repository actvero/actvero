import { useRef, useState } from 'react'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

const repository =
  'https://github.com/actvero/actvero-harness/blob/main/actvero'
const guide = `请为当前项目配置 Actvero 工作台开发指引。

先阅读官方开发手册：${repository}/workbench-development.zh.md
再读取开发 Skill：${repository}/skills/actvero-workbench-development/SKILL.md
本地已有 Actvero Harness 源码时，优先读取与目标桌面端版本匹配的仓库文件。

检查当前项目是已有工作台还是新项目。把开发手册入口补到项目现有的开发说明里；如果你支持项目级 Skill，将官方 Skill 放到你能识别的项目技能目录，保留已有同名文件中的项目约定。随后说明从哪里开始开发、如何打包和验收。

需要让组织管理员配置服务地址等参数时，在安装包 package.json 的 dsh.actveroWorkbenchConfig 中声明字段，客户端通过 await workbench.config() 读取。请按手册核对字段和凭据处理，保留现有包名与业务代码。完成配置后，告诉我更新了哪些本地文件以及下一步怎么做。`

export function WorkbenchDevelopmentGuide() {
  const button = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(guide)
      toast.success('已复制开发指引，可粘贴给本地 Agent')
    } catch {
      setOpen(true)
    }
  }

  return (
    <>
      <Button ref={button} variant='outline' onClick={() => void copy()}>
        <Copy />
        复制开发指引
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            button.current?.focus()
          }}
        >
          <DialogHeader>
            <DialogTitle>工作台开发指引</DialogTitle>
            <DialogDescription>
              浏览器无法访问剪贴板，请手动复制以下内容，粘贴给本地 Agent。
            </DialogDescription>
          </DialogHeader>
          <Textarea
            aria-label='工作台开发指引内容'
            readOnly
            value={guide}
            onFocus={(event) => event.currentTarget.select()}
            className='min-h-60'
          />
        </DialogContent>
      </Dialog>
    </>
  )
}
