import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from '@/components/ui/card'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { LoadingState, RequestError } from '@/components/request-state'
import { Choice } from './controls'
import { useKnowledge, useKnowledgeData } from './shared'

export function KnowledgeDefaults() {
  const query = useKnowledgeData<Schema['KnowledgeDefaultsView']>(
    '/knowledge/defaults'
  )
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return <DefaultsForm key={query.data.version} data={query.data} />
}
function DefaultsForm({ data }: { data: Schema['KnowledgeDefaultsView'] }) {
  const { csrf, refresh } = useKnowledge()
  const [embedding, setEmbedding] = useState(data.embedding_model_id ?? 'none')
  const [rerank, setRerank] = useState(data.rerank_model_id ?? 'none')
  const [enabled, setEnabled] = useState(data.rerank_enabled ?? false)
  const [secret, setSecret] = useState('')
  const save = useMutation({
    mutationFn: () =>
      api(
        '/knowledge/defaults',
        'PUT',
        {
          version: data.version,
          embedding_model_id: embedding === 'none' ? null : embedding,
          rerank_model_id: rerank === 'none' ? null : rerank,
          rerank_enabled: enabled,
        },
        csrf
      ),
    onSuccess: () => {
      toast.success('默认配置已保存')
      void refresh()
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  const add = useMutation({
    mutationFn: () =>
      api(
        '/knowledge/credentials/batch',
        'POST',
        {
          keys: secret
            .split(/[,，\n]+/)
            .map((key) => key.trim())
            .filter(Boolean),
        },
        csrf
      ),
    onSuccess: () => {
      setSecret('')
      void refresh()
      toast.success('解析凭据已保存')
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  const toggle = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) =>
      api(
        `/knowledge/credentials/${id}?enabled=${value}`,
        'PUT',
        undefined,
        csrf
      ),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(messageOf(e)),
  })
  return (
    <div className='flex max-w-5xl flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>默认索引与检索</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel>向量模型</FieldLabel>
              <Choice
                label='向量模型'
                value={embedding}
                onChange={setEmbedding}
                items={[
                  { value: 'none', label: '暂不配置' },
                  ...data.models
                    .filter((m) => m.kind === 'embedding')
                    .map((m) => ({
                      value: m.id,
                      label: `${m.name} · ${m.dimensions ?? '未设置'} 维`,
                    })),
                ]}
              />
            </Field>
            <Field orientation='horizontal'>
              <FieldLabel htmlFor='rerank-enabled'>启用重排序</FieldLabel>
              <Switch
                id='rerank-enabled'
                checked={enabled}
                onCheckedChange={setEnabled}
              />
            </Field>
            {enabled && (
              <Field>
                <FieldLabel>重排序模型</FieldLabel>
                <Choice
                  label='重排序模型'
                  value={rerank}
                  onChange={setRerank}
                  items={[
                    { value: 'none', label: '请选择模型' },
                    ...data.models
                      .filter((m) => m.kind === 'rerank')
                      .map((m) => ({ value: m.id, label: m.name })),
                  ]}
                />
              </Field>
            )}
            <Alert>
              <AlertDescription>
                保存后以当前账号调用并计入其额度。当前授权人：
                {data.executor_name ?? '尚未授权'}。
              </AlertDescription>
            </Alert>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            保存默认配置
          </Button>
        </CardFooter>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>MinerU 解析器</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-4'>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              add.mutate()
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor='mineru-keys'>API Key</FieldLabel>
                <div className='flex flex-col gap-3 sm:flex-row'>
                  <Input
                    id='mineru-keys'
                    type='password'
                    autoComplete='off'
                    placeholder='多个 Key 用逗号分隔'
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                    maxLength={81940}
                    required
                  />
                  <Button
                    type='submit'
                    disabled={add.isPending || !secret.trim()}
                  >
                    添加 Key
                  </Button>
                </div>
              </Field>
            </FieldGroup>
          </form>
          {data.credentials.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>启用</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.credentials.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.name}</TableCell>
                    <TableCell>
                      {!c.enabled ? '已停用' : c.error || '已配置'}
                    </TableCell>
                    <TableCell>
                      <Switch
                        aria-label={`启用 ${c.name}`}
                        checked={c.enabled}
                        disabled={toggle.isPending}
                        onCheckedChange={(v) =>
                          toggle.mutate({ id: c.id, value: v })
                        }
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className='text-sm text-muted-foreground'>尚未配置</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
