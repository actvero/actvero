import { useFormContext, useWatch } from 'react-hook-form'
import { dateTime } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import type { ModelValues } from './model-form'

export function ReferenceSnapshots({
  disabled = false,
}: {
  disabled?: boolean
}) {
  const form = useFormContext<ModelValues>()
  const snapshots =
    useWatch({ control: form.control, name: 'quote_snapshots' }) ?? []
  return (
    <CollapsibleSection title={`已保存参考报价（${snapshots.length}）`}>
      <p className='mb-3 text-sm text-muted-foreground'>
        快照仅记录公开来源，不改变成员预算价格、渠道采购价格或调用权限。
      </p>
      {snapshots.length === 0 ? (
        <p className='text-sm text-muted-foreground'>尚未保存参考报价。</p>
      ) : (
        <div className='flex flex-col gap-3'>
          {snapshots.map((snapshot, index) => (
            <article
              key={`${snapshot.provider}/${snapshot.model_id}/${snapshot.fetched_at}/${index}`}
              className='min-w-0 rounded-md border bg-background p-3'
            >
              <div className='flex flex-wrap items-start justify-between gap-2'>
                <div className='min-w-0'>
                  <h4 className='font-medium break-all'>
                    {snapshot.provider} / {snapshot.model_id}
                  </h4>
                  <p className='text-xs text-muted-foreground'>
                    抓取于 {dateTime(snapshot.fetched_at)} · {snapshot.currency}{' '}
                    / {snapshot.unit} {snapshot.metric}
                    {snapshot.source_updated_at &&
                      ` · 来源更新 ${snapshot.source_updated_at}`}
                  </p>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      disabled={disabled}
                    >
                      移除参考报价
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>从草稿移除参考报价？</AlertDialogTitle>
                      <AlertDialogDescription>
                        将移除 {snapshot.provider} / {snapshot.model_id}{' '}
                        的这份来源快照。成员预算价与渠道采购价保持原值；保存模型后才会写入变更。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => {
                          const latest = form.getValues('quote_snapshots') ?? []
                          form.setValue(
                            'quote_snapshots',
                            latest.filter(
                              (_, itemIndex) => itemIndex !== index
                            ),
                            {
                              shouldDirty: true,
                              shouldValidate: true,
                            }
                          )
                        }}
                      >
                        移除快照
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
              {snapshot.source_url && (
                <a
                  href={snapshot.source_url}
                  target='_blank'
                  rel='noreferrer'
                  className='mt-2 inline-block text-xs break-all underline'
                >
                  来源文档
                </a>
              )}
              <dl className='mt-3 grid gap-2 text-xs sm:grid-cols-2'>
                {Object.entries(snapshot.raw_cost ?? {}).map(([key, value]) => (
                  <div key={key} className='min-w-0 rounded border p-2'>
                    <dt className='font-medium break-all'>{key}</dt>
                    <dd className='mt-1 break-all text-muted-foreground'>
                      {typeof value === 'string'
                        ? value
                        : JSON.stringify(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              {!!snapshot.conditions?.length && (
                <div className='mt-3'>
                  <p className='text-xs font-medium'>未解决条件</p>
                  <ul className='mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground'>
                    {snapshot.conditions.map((condition, itemIndex) => (
                      <li key={itemIndex} className='break-words'>
                        {condition}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </CollapsibleSection>
  )
}
