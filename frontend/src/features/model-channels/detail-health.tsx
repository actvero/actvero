import { useRef, useState } from 'react'
import { api, ApiError, dateTime } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { RequestError } from '@/components/request-state'
import { ModelEditor } from '@/features/model-catalog/model-editor'
import type { Model } from '@/features/model-catalog/model-form'
import { HealthBadge, ManualBadge, type Detail } from './shared'
import type { TestOperation } from './test-operations'

const stateLabels: Record<string, string> = {
  ready: '可调度',
  unverified: '待验证',
  unavailable: '不可用',
  disabled: '绑定已关闭',
  model_archived: '模型已归档',
  model_disabled: '模型已关闭',
  operation_disabled: '操作已关闭',
  credential_error: '凭据阻断',
  model_error: '上游模型阻断',
  binding_error: '绑定拒绝待判',
  incompatible: '不兼容',
  cooldown: '冷却中',
  probing: '探测中',
}

function blockExplanation(
  state: string,
  reason?: string | null
): string | null {
  if (state === 'credential_error')
    return '可靠的渠道凭据拒绝；同一渠道凭据范围受阻，请核对凭据。'
  if (state === 'model_error')
    return reason === 'model_unavailable'
      ? '上游确认此模型不可用；相关模型目标受阻，其他模型不因此关闭。'
      : '上游模型目标受阻；其他模型不因此关闭。'
  if (state === 'binding_error')
    return reason === 'unclassified_rejection'
      ? '上游 403/404 的原因尚未判明；仅此绑定暂停，不能推断整个渠道凭据失效。'
      : '拒绝范围尚未判明；仅此绑定暂停。'
  if (state === 'cooldown')
    return '该绑定正在等待重试；截止时间以服务端记录为准，到时也需服务端重新判定。'
  return null
}

export function DetailHealth({
  channel,
  showTest,
  testOperations,
  onChanged,
}: {
  channel: Detail
  showTest: (id: string, operation: TestOperation, bindingId?: string) => void
  testOperations: TestOperation[]
  onChanged?: () => void
}) {
  const [model, setModel] = useState<Model | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [permissionLost, setPermissionLost] = useState(false)
  const editorTrigger = useRef<HTMLElement | null>(null)
  const references = channel.binding_references ?? []
  const active = references.filter(
    (item) =>
      !item.model_archived &&
      item.model_enabled &&
      item.operation_enabled &&
      item.binding_enabled
  )
  const blocked = active.filter(
    (item) => !['ready', 'unverified'].includes(item.health_state)
  )
  async function openModel(id: string) {
    editorTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    setBusy(true)
    setError(null)
    try {
      setModel(await api<Model>('/llm/models/' + id))
    } catch (cause) {
      setError(cause)
      if (cause instanceof ApiError && cause.status === 403)
        setPermissionLost(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className='flex min-w-0 flex-col gap-4 pt-4'>
      <Card>
        <CardHeader>
          <CardTitle>渠道状态与自动保护</CardTitle>
          <CardDescription>
            渠道开关和绑定健康分别计算；目录检查不会改变推理健康。
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-col gap-3 text-sm'>
          <div className='flex flex-wrap gap-2'>
            <ManualBadge channel={channel} />
            <HealthBadge channel={channel} />
            {channel.archived && <Badge variant='secondary'>已归档</Badge>}
            <Badge variant='outline'>
              自动保护{channel.automatic_protection?.enabled ? '开启' : '关闭'}
            </Badge>
          </div>
          <p>
            已启用的关联绑定 {active.length} 条 · 就绪{' '}
            {active.filter((item) => item.health_state === 'ready').length} 条 ·
            阻断或等待 {blocked.length} 条
          </p>
          {!!channel.health_summary && (
            <p className='text-muted-foreground'>
              健康汇总时间：{dateTime(channel.health_summary.as_of)}
            </p>
          )}
          {!channel.manual_enabled && (
            <p>渠道已停用，成员调用仍被阻止；管理员可以显式选择渠道诊断。</p>
          )}
          {!active.length && (
            <p className='text-muted-foreground'>
              未关联可调用模型。登记上游模型本身不会开放成员调用。
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>关联模型与绑定健康</CardTitle>
          <CardDescription>
            只读展示当前模型、操作与绑定状态。修改绑定请进入平台模型配置。
          </CardDescription>
        </CardHeader>
        <CardContent className='flex min-w-0 flex-col gap-3'>
          {references.length ? (
            references.map((reference) => {
              const reason = reference.health_block_reason
              const explanation = blockExplanation(
                reference.health_state,
                reason
              )
              // Historical protection records do not gate SDK dispatch.
              const waiting = reference.health_state === 'cooldown'
              return (
                <div
                  key={reference.binding_id}
                  className='flex min-w-0 flex-col gap-2 rounded-md border p-3'
                >
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <div className='min-w-0'>
                      <p className='font-medium break-all'>
                        {reference.model_name} · {reference.operation}
                      </p>
                      <p className='font-mono text-xs break-all text-muted-foreground'>
                        {reference.upstream_model_id}
                      </p>
                    </div>
                    <Badge
                      variant={
                        reference.health_state === 'ready'
                          ? 'success'
                          : 'outline'
                      }
                    >
                      {stateLabels[reference.health_state] ??
                        reference.health_state}
                    </Badge>
                  </div>
                  <div className='flex flex-wrap gap-2 text-xs text-muted-foreground'>
                    <span>
                      绑定 {reference.binding_enabled ? '开启' : '关闭'}
                    </span>
                    <span>
                      模型 {reference.model_enabled ? '开启' : '关闭'}
                    </span>
                    <span>
                      操作 {reference.operation_enabled ? '开启' : '关闭'}
                    </span>
                    {!reference.source_registered && <span>来源未登记</span>}
                    {reference.tested_at && (
                      <span>最近测试 {dateTime(reference.tested_at)}</span>
                    )}
                    {reference.cooldown_until && (
                      <span>冷却截止 {dateTime(reference.cooldown_until)}</span>
                    )}
                  </div>
                  {explanation && (
                    <p className='text-xs text-muted-foreground'>
                      {explanation}
                    </p>
                  )}
                  {waiting && (
                    <p className='text-xs text-muted-foreground'>
                      历史冷却状态仅供排障，实际调用由执行服务调度。
                    </p>
                  )}
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      disabled={busy || permissionLost}
                      onClick={() => void openModel(reference.model_id)}
                    >
                      查看模型绑定
                    </Button>
                    {!channel.archived &&
                      reference.source_registered &&
                      testOperations.includes(
                        reference.operation as TestOperation
                      ) && (
                        <Button
                          type='button'
                          variant='ghost'
                          size='sm'
                          disabled={busy || permissionLost}
                          onClick={() =>
                            showTest(
                              reference.upstream_model_id,
                              reference.operation as TestOperation
                            )
                          }
                        >
                          诊断此绑定
                        </Button>
                      )}
                    {!channel.archived &&
                      !reference.model_archived &&
                      reference.source_registered &&
                      reference.model_version &&
                      testOperations.includes(
                        reference.operation as TestOperation
                      ) && (
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          disabled={busy || permissionLost}
                          onClick={() =>
                            showTest(
                              reference.upstream_model_id,
                              reference.operation as TestOperation,
                              reference.binding_id
                            )
                          }
                        >
                          验证此绑定
                        </Button>
                      )}
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    测试只记录此绑定的结果，不改变渠道、模型或绑定开关；实际调用独立调度。
                  </p>
                </div>
              )
            })
          ) : (
            <p className='text-sm text-muted-foreground'>
              此渠道没有关联绑定。
            </p>
          )}
        </CardContent>
      </Card>
      {!!error && <RequestError error={error} />}
      {!channel.automatic_protection?.enabled && (
        <Alert>
          <AlertTitle>一般故障自动保护已关闭</AlertTitle>
          <AlertDescription>
            已关闭一般故障冷却。认证错误和上游限流仍由执行服务处理；平台不再根据历史测试结果阻止调用。
          </AlertDescription>
        </Alert>
      )}
      {model && (
        <ModelEditor
          model={model}
          close={() => {
            setModel(null)
            editorTrigger.current?.focus()
          }}
          saved={() => {
            setModel(null)
            onChanged?.()
            editorTrigger.current?.focus()
          }}
        />
      )}
    </div>
  )
}
