import { useFormContext, useWatch } from 'react-hook-form'
import { CheckCircle2, Circle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { activationDraft, issueTab } from './model-activation'
import { modelSchema, type ModelValues } from './model-form'

export function ModelReadiness({
  navigate,
}: {
  navigate: (tab: string) => void
}) {
  const form = useFormContext<ModelValues>()
  useWatch({ control: form.control })
  const draft = activationDraft(form.getValues())
  const parsed = modelSchema.safeParse(draft)
  const issues = parsed.success ? [] : parsed.error.issues
  const sourceReady = draft.bindings.some(
    (binding) =>
      binding.enabled &&
      (draft.routing.mode === 'auto' ||
        (binding.channel_id === draft.access.channel_id &&
          binding.upstream_id === draft.access.upstream_id))
  )
  const checks = [
    { tab: 'bindings', label: '调用来源', ready: sourceReady },
    {
      tab: 'profile',
      label: '模型参数',
      ready: !issues.some((issue) => issueTab(issue.path) === 'profile'),
    },
    {
      tab: 'prices',
      label: '成员预算价格',
      ready:
        draft.budget_price.enabled &&
        !issues.some((issue) => issueTab(issue.path) === 'prices'),
    },
    {
      tab: 'access',
      label:
        draft.access.audience === 'administrators'
          ? '仅管理员使用'
          : draft.access.audience === 'organization'
            ? '组织全员使用'
            : `${draft.access.member_ids.length} 位指定成员`,
      ready: !issues.some((issue) => issueTab(issue.path) === 'access'),
    },
  ]
  return (
    <div className='mb-4 rounded-lg border bg-muted/30 p-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='mr-2 text-sm font-medium'>启用前核对</span>
        {checks.map((check) => (
          <Button
            key={check.tab}
            type='button'
            size='sm'
            variant='ghost'
            onClick={() => navigate(check.tab)}
          >
            {check.ready ? (
              <CheckCircle2 className='text-primary' />
            ) : (
              <Circle className='text-muted-foreground' />
            )}
            {check.label}
            {!check.ready && ' · 待配置'}
          </Button>
        ))}
      </div>
      <p className='mt-2 text-xs text-muted-foreground'>
        点击“保存并启用”会启用当前用途和固定来源，并检查渠道状态及积分换算。其他用途的开关保持当前设置。
      </p>
    </div>
  )
}
