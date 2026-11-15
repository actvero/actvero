import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Check } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import { LoadingState, RequestError } from '@/components/request-state'
import { UploadButton } from './document-upload'
import { BaseFields, ChunkFields } from './forms'
import { SavedKnowledgeIcon } from './icon'
import { RetrievalFields } from './retrieval-fields'
import {
  chunkingError,
  defaultsPath,
  initial,
  organizationRetrieval,
  retrievalError,
  retrievalLabels,
  useKnowledge,
  useKnowledgeData,
  type Base,
  type BaseInput,
  type Defaults,
  type RetrievalPolicy,
} from './shared'

const steps = ['基本信息', '切片与检索', '导入文档']

export function CreateKnowledge({
  onCreated,
}: {
  onCreated: (id: string) => void
}) {
  const { csrf, refresh } = useKnowledge()
  const [step, setStep] = useState(0)
  const [body, setBody] = useState<BaseInput>(initial)
  const [created, setCreated] = useState<Base>()
  const [custom, setCustom] = useState<RetrievalPolicy | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploaded, setUploaded] = useState(false)
  const defaults = useKnowledgeData<Defaults>(defaultsPath)
  const policy =
    custom ?? (defaults.data ? organizationRetrieval(defaults.data) : null)
  const policyError =
    policy && defaults.data ? retrievalError(policy, defaults.data) : undefined
  const chunking = body.chunking ?? initial.chunking!
  const create = useMutation({
    mutationFn: () =>
      api<Base>(
        '/knowledge',
        'POST',
        {
          ...body,
          ...(custom
            ? { retrieval: custom }
            : { defaults_version: defaults.data?.version }),
        },
        csrf
      ),
    onSuccess: (base) => {
      setCreated(base)
      setStep(2)
      void refresh()
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void defaults.refetch()
    },
  })
  const canCreate =
    defaults.isSuccess &&
    !defaults.isFetching &&
    !policyError &&
    !chunkingError(chunking) &&
    !create.isPending

  return (
    <div className='mx-auto flex w-full max-w-5xl min-w-0 flex-col gap-5'>
      <ol
        className='grid grid-cols-3 divide-x overflow-hidden rounded-lg border bg-muted/30'
        aria-label='创建进度'
      >
        {steps.map((label, index) => (
          <li
            key={label}
            aria-current={step === index ? 'step' : undefined}
            className={cn(
              'flex min-w-0 flex-col items-center justify-center gap-2 px-2 py-3 text-center text-xs sm:flex-row sm:px-4 sm:text-sm',
              step === index
                ? 'bg-muted font-semibold'
                : 'text-muted-foreground'
            )}
          >
            <span
              aria-hidden
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full',
                step === index
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
              )}
            >
              {step > index ? <Check className='size-3.5' /> : index + 1}
            </span>
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <Card>
        {created ? (
          <>
            <CardHeader layout='row' className='gap-3 px-6'>
              <SavedKnowledgeIcon
                base={created}
                editable
                onSaved={setCreated}
              />
              <div className='flex min-w-0 flex-col gap-1.5'>
                <CardTitle className='wrap-anywhere'>{created.name}</CardTitle>
                <CardDescription>
                  PDF 和图片会发送至配置的 MinerU 服务解析。
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <UploadButton
                baseId={created.id}
                dropzone
                onUploadingChange={setUploading}
                onComplete={() => setUploaded(true)}
              />
            </CardContent>
            <CardFooter className='justify-end'>
              <Button
                variant={uploaded ? 'default' : 'outline'}
                disabled={uploading}
                onClick={() => onCreated(created.id)}
              >
                {uploaded ? '进入文档' : '跳过上传'}
                <ArrowRight data-icon='inline-end' />
              </Button>
            </CardFooter>
          </>
        ) : step === 0 ? (
          <form
            className='flex flex-col gap-6'
            onSubmit={(event) => {
              event.preventDefault()
              if (body.name.trim()) setStep(1)
            }}
          >
            <CardContent>
              <BaseFields value={body} onChange={setBody} />
            </CardContent>
            <CardFooter className='justify-end'>
              <Button type='submit' disabled={!body.name.trim()}>
                下一步 <ArrowRight data-icon='inline-end' />
              </Button>
            </CardFooter>
          </form>
        ) : (
          <>
            <CardContent className='flex flex-col gap-6'>
              <ChunkFields
                value={chunking}
                onChange={(value) => setBody({ ...body, chunking: value })}
              />
              <div className='border-t pt-5'>
                {defaults.isPending ? (
                  <LoadingState />
                ) : defaults.isError ? (
                  <RequestError
                    error={defaults.error}
                    retry={() => void defaults.refetch()}
                  />
                ) : (
                  policy && (
                    <CollapsibleSection
                      title={
                        <span className='flex flex-wrap items-baseline gap-x-3 gap-y-1 text-left'>
                          <span>检索配置</span>
                          <span className='text-xs font-normal text-muted-foreground'>
                            {custom ? '自定义' : '组织默认'} ·{' '}
                            {retrievalLabels[policy.mode ?? 'keyword']}
                            {policy.rerank_model_id ? ' · 已开启重排序' : ''}
                          </span>
                        </span>
                      }
                    >
                      <RetrievalFields
                        value={policy}
                        onChange={setCustom}
                        data={defaults.data}
                        onReset={custom ? () => setCustom(null) : undefined}
                      />
                    </CollapsibleSection>
                  )
                )}
                {policyError && (
                  <p role='alert' className='mt-2 text-sm text-destructive'>
                    {policyError}
                  </p>
                )}
              </div>
              {create.isError && <RequestError error={create.error} />}
            </CardContent>
            <CardFooter className='justify-end gap-2'>
              <Button
                variant='outline'
                disabled={create.isPending}
                onClick={() => setStep(0)}
              >
                上一步
              </Button>
              <Button disabled={!canCreate} onClick={() => create.mutate()}>
                {create.isPending ? '创建中…' : '创建并继续'}
                <ArrowRight data-icon='inline-end' />
              </Button>
            </CardFooter>
          </>
        )}
      </Card>
    </div>
  )
}
