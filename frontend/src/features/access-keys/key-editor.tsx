import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { CopyableField } from '@/components/copyable-field'
import { RequestError } from '@/components/request-state'
import { KnowledgeGrants } from './knowledge-grants'

const schema = z.object({
  name: z.string().trim().min(1, '请输入名称').max(100),
})

export function KeyEditor({
  csrf,
  rules,
  onClose,
  onCreated,
  restore,
}: {
  csrf: string
  rules: Schema['KeyPolicyView']
  onClose: () => void
  onCreated: () => void
  restore: () => void
}) {
  const [creationId] = useState(() => crypto.randomUUID())
  const [created, setCreated] = useState<Schema['KeyCreated'] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [purpose, setPurpose] = useState('models')
  const [bases, setBases] = useState<string[]>([])
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: '' },
  })
  const busy = form.formState.isSubmitting
  async function save(values: z.infer<typeof schema>) {
    setError(null)
    try {
      const result = await api<Schema['KeyCreated']>(
        '/account/access-keys',
        'POST',
        {
          creation_id: creationId,
          name: values.name,
          ...(purpose === 'knowledge'
            ? {
                grants: bases.map((resource_id) => ({
                  kind: 'knowledge',
                  resource_id,
                  actions: ['read', 'invoke'],
                })),
              }
            : {}),
        },
        csrf
      )
      setCreated(result) // Never store the secret in query/mutation caches or browser storage.
      onCreated()
    } catch (e) {
      setError(e)
      onCreated()
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy && !created) onClose()
      }}
    >
      <DialogContent
        className='max-h-[90dvh] overflow-y-auto'
        aria-describedby={created ? 'key-created-description' : undefined}
        showCloseButton={!busy && !created}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
        onInteractOutside={(e) => {
          if (busy || created) e.preventDefault()
        }}
        onEscapeKeyDown={(e) => {
          if (busy || created) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>{created ? '密钥已创建' : '创建访问密钥'}</DialogTitle>
          {created && (
            <DialogDescription id='key-created-description'>
              可在密钥列表中再次查看或复制。
            </DialogDescription>
          )}
        </DialogHeader>
        {created ? (
          <div className='flex min-w-0 flex-col gap-4'>
            <CopyableField
              value={created.secret}
              label='API Key'
              copyLabel='复制密钥'
            />
            <DialogFooter>
              <Button
                onClick={() => {
                  setCreated(null)
                  onClose()
                }}
              >
                已保存，关闭
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(save)}
              className='flex flex-col gap-4'
            >
              <fieldset disabled={busy} className='flex min-w-0 flex-col gap-4'>
                <FormField
                  control={form.control}
                  name='name'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>名称</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          placeholder='例如：本地 Agent'
                          maxLength={100}
                          autoComplete='off'
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className='flex flex-col gap-3'>
                  <Label>用途</Label>
                  <RadioGroup
                    aria-label='密钥用途'
                    value={purpose}
                    onValueChange={setPurpose}
                  >
                    <Label className='flex items-center gap-2'>
                      <RadioGroupItem value='models' />
                      模型与 MCP 调用
                    </Label>
                    <Label className='flex items-center gap-2'>
                      <RadioGroupItem value='knowledge' />
                      知识库检索与原文阅读
                    </Label>
                  </RadioGroup>
                  {purpose === 'knowledge' && (
                    <KnowledgeGrants value={bases} onChange={setBases} />
                  )}
                </div>
              </fieldset>
              {error != null && <RequestError error={error} />}
              <DialogFooter>
                <Button
                  type='button'
                  variant='outline'
                  disabled={busy}
                  onClick={onClose}
                >
                  取消
                </Button>
                <Button
                  type='submit'
                  disabled={
                    busy ||
                    !rules.enabled ||
                    (purpose === 'knowledge' && !bases.length)
                  }
                >
                  {busy ? '正在创建…' : '创建密钥'}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  )
}
