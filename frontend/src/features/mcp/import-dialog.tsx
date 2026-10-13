import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { JsonEditor } from '@/components/ui/json-editor'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { RequestError } from '@/components/request-state'
import { useReturnFocus, useMcp, authNames } from './shared'

export function ImportDialog({ close }: { close: () => void }) {
  const restoreFocus = useReturnFocus()
  const { write, rememberSaved, discoverSaved } = useMcp()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [preview, setPreview] = useState<Schema['McpImportPreview'] | null>(
    null
  )
  // Raw configuration, including secrets, lives only in this dialog's form state.
  const form = useForm({
    resolver: zodResolver(
      z.object({
        json: z
          .string()
          .min(1, '请粘贴配置 JSON')
          .max(2_000_000, '配置不能超过 2 MB'),
      })
    ),
    defaultValues: { json: '' },
  })
  function configuration() {
    try {
      const v: unknown = JSON.parse(form.getValues('json'))
      if (!v || Array.isArray(v) || typeof v !== 'object') throw Error()
      return v
    } catch {
      throw Error('JSON 格式无效，请检查括号、逗号和引号')
    }
  }
  async function confirm() {
    setPending(true)
    setError(null)
    try {
      const saved = await write<Schema['McpServicePage']>('/import', 'POST', {
        configuration: configuration(),
      })
      form.reset()
      setPreview(null)
      rememberSaved(saved.items)
      void discoverSaved(saved.items)
      close()
    } catch (e) {
      setError(e)
      setPreview(null)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !pending) close()
      }}
    >
      <DialogContent
        onCloseAutoFocus={restoreFocus}
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-5xl'
        onPointerDownOutside={(e) => {
          if (pending || form.formState.isDirty) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>{preview ? '确认导入' : '导入 MCP 服务'}</DialogTitle>
          <DialogDescription>
            {preview
              ? '检查配置后确认导入。所有服务默认关闭，启用后默认组织全员可用。'
              : '粘贴 mcpServers 或 Actvero 导出配置，先预览再导入。'}
          </DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className='flex flex-col gap-4'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>服务</TableHead>
                  <TableHead>连接方式</TableHead>
                  <TableHead>认证</TableHead>
                  <TableHead>检查结果</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.items.map((item, i) => (
                  <TableRow key={i}>
                    <TableCell className='max-w-48 break-words whitespace-normal'>
                      {item.name}
                    </TableCell>
                    <TableCell>
                      {item.transport === 'http'
                        ? 'Streamable HTTP'
                        : item.transport === 'sse'
                          ? 'SSE'
                          : item.transport}
                    </TableCell>
                    <TableCell>
                      {authNames[item.auth_mode as keyof typeof authNames] ||
                        '待检查'}
                      {item.has_credentials && (
                        <p className='text-xs text-muted-foreground'>
                          •••••• · {item.credential_count} 项密钥
                        </p>
                      )}
                    </TableCell>
                    <TableCell className='max-w-64 whitespace-normal'>
                      {item.error ? (
                        <p className='text-sm text-destructive'>{item.error}</p>
                      ) : (
                        <Badge variant='outline'>可导入</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {preview.items.some((i) => i.has_credentials) && (
              <Alert>
                <AlertDescription>
                  配置中的密钥将加密保存为组织凭据，由获授权成员共用。若应由每位成员填写，请返回修改配置。
                </AlertDescription>
              </Alert>
            )}
            {!preview.valid && (
              <Alert>
                <AlertDescription>
                  请返回修正配置后重新预览，本次尚未导入任何服务。
                </AlertDescription>
              </Alert>
            )}
            {!!error && <RequestError error={error} />}
            <DialogFooter>
              <Button
                variant='outline'
                disabled={pending}
                onClick={() => {
                  setPreview(null)
                  setError(null)
                }}
              >
                返回修改
              </Button>
              <Button
                disabled={pending || !preview.valid}
                onClick={() => void confirm()}
              >
                {pending
                  ? '导入中…'
                  : `确认导入 ${preview.items.length} 个服务`}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <Form {...form}>
            <form
              className='flex flex-col gap-4'
              onSubmit={form.handleSubmit(async () => {
                setPending(true)
                setError(null)
                try {
                  setPreview(
                    await write<Schema['McpImportPreview']>(
                      '/import/preview',
                      'POST',
                      { configuration: configuration() }
                    )
                  )
                } catch (e) {
                  setError(e)
                } finally {
                  setPending(false)
                }
              })}
            >
              <FormField
                control={form.control}
                name='json'
                render={({ field }) => (
                  <FormItem>
                    <div className='flex items-center justify-between gap-3'>
                      <FormLabel onClick={() => form.setFocus('json')}>
                        配置 JSON
                      </FormLabel>
                      <div className='flex items-center gap-1'>
                        {!field.value.trim() && (
                          <Button
                            type='button'
                            variant='ghost'
                            size='sm'
                            disabled={pending}
                            onClick={() => {
                              form.setValue(
                                'json',
                                JSON.stringify(
                                  {
                                    mcpServers: {
                                      文档服务: {
                                        type: 'streamable-http',
                                        url: 'https://example.com/mcp',
                                      },
                                    },
                                  },
                                  null,
                                  2
                                ),
                                { shouldDirty: true }
                              )
                              form.clearErrors('json')
                              setError(null)
                              form.setFocus('json')
                            }}
                          >
                            填入示例
                          </Button>
                        )}
                        <Button
                          type='button'
                          variant='ghost'
                          size='sm'
                          disabled={pending || !field.value.trim()}
                          onClick={() => {
                            try {
                              const formatted = JSON.stringify(
                                JSON.parse(field.value),
                                null,
                                2
                              )
                              form.setValue('json', formatted, {
                                shouldDirty: true,
                              })
                              form.clearErrors('json')
                              setError(null)
                            } catch {
                              form.setError('json', {
                                message:
                                  'JSON 格式无效，请检查括号、逗号和引号',
                              })
                            }
                          }}
                        >
                          格式化
                        </Button>
                      </div>
                    </div>
                    <FormControl>
                      <JsonEditor
                        {...field}
                        aria-label='配置 JSON'
                        disabled={pending}
                        placeholder='在此粘贴 MCP 配置 JSON…'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {!!error && <RequestError error={error} />}
              <DialogFooter>
                <Button
                  type='button'
                  variant='outline'
                  disabled={pending}
                  onClick={close}
                >
                  取消
                </Button>
                <Button disabled={pending}>
                  {pending ? '检查中…' : '预览配置'}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  )
}
