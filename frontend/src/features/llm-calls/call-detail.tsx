import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { CopyableField } from '@/components/copyable-field'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ReconcileDialog } from '@/features/quota-policies/reconcile-dialog'
import { operations, results, settlements } from './filters'
import { timeInZone } from './time'

type Detail = Schema['CallDetail']
type Attempt = Schema['CallAttemptView']

function statusText(value: string | null | undefined) {
  return value ?? '未知'
}
function truth(value: boolean | null) {
  return value === true ? '是' : value === false ? '否' : '未记录'
}
function metricLabel(metric: string, field: string) {
  const names: Record<string, string> = {
    input_tokens: '输入 Token',
    output_tokens: '输出 Token',
    cache_read_tokens: '缓存读取 Token',
    cache_write_5m_tokens: '缓存写入 5 分钟 Token',
    cache_write_1h_tokens: '缓存写入 1 小时 Token',
    input_characters: '字符',
    search_units: '搜索单位',
    image_count: '交付张数',
  }
  return names[field] ?? `${metric} · ${field}`
}

function PriceSnapshot({ price }: { price: Schema['PriceSnapshotView'] }) {
  const rates = [
    ['输入', price.input],
    ['输出', price.output],
    ['缓存读取', price.cache_read],
    ['缓存写入 5 分钟', price.cache_write_5m],
    ['缓存写入 1 小时', price.cache_write_1h],
  ] as const
  return (
    <p className='text-sm break-words text-muted-foreground'>
      {price.metric} ·{' '}
      {rates
        .filter(([, value]) => value !== null)
        .map(
          ([name, value]) =>
            `${name} ${value} ${price.currency} / ${price.unit}`
        )
        .join(' · ')}
    </p>
  )
}

function AttemptCard({ attempt }: { attempt: Attempt }) {
  const ended = attempt.upstream_terminal === true
  return (
    <Card className='min-w-0'>
      <CardHeader className='pb-2'>
        <CardTitle size='body'>
          尝试 {attempt.number ?? '—'} · {statusText(attempt.status)}
        </CardTitle>
        <p className='text-xs break-all text-muted-foreground'>
          尝试号 {attempt.attempt_id ?? '历史记录无独立编号'}
        </p>
      </CardHeader>
      <CardContent className='grid min-w-0 gap-2 text-sm'>
        <p className='break-words'>
          {attempt.channel_name ?? '渠道未记录'} · 上游模型{' '}
          {attempt.upstream_id ?? '未记录'}
        </p>
        <p>
          发送：{truth(attempt.sent)} · 有效输出：
          {truth(attempt.output_started)} · 上游终止：
          {truth(attempt.upstream_terminal)}
        </p>
        <p>
          客户端编码终止：{truth(attempt.client_terminal)}
          ；此项不证明用户设备已收到。
        </p>
        <p>
          耗时{' '}
          {attempt.duration_ms === null ? '未知' : `${attempt.duration_ms} ms`}{' '}
          · 首输出{' '}
          {attempt.first_output_ms === null
            ? '未知'
            : `${attempt.first_output_ms} ms`}{' '}
          · HTTP {attempt.upstream_status ?? '未记录'}
        </p>
        {(attempt.error_scope ||
          attempt.error_code ||
          attempt.retry_reason) && (
          <p className='break-words'>
            归因 {attempt.error_scope ?? '未分类'} · 代码{' '}
            {attempt.error_code ?? '—'} · 重试原因 {attempt.retry_reason ?? '—'}
            {attempt.retry_after_seconds !== null
              ? ` · 建议等待 ${attempt.retry_after_seconds} 秒`
              : ''}
          </p>
        )}
        {attempt.sent === false && attempt.certainly_unused === true && (
          <Badge variant='secondary' className='self-start'>
            发送前失败，确认未使用
          </Badge>
        )}
        {(attempt.uncertain || (attempt.sent === true && !ended)) && (
          <Alert>
            <AlertTitle>用量或交付待确认</AlertTitle>
            <AlertDescription>
              请求已发送，缺少完整终止证据；不能按零计量。
            </AlertDescription>
          </Alert>
        )}
        <div className='grid min-w-0 gap-1'>
          <p className='font-medium'>原始计量证据</p>
          {attempt.usage_evidence.length ? (
            attempt.usage_evidence.map((item, index) => (
              <p
                key={`${item.field}-${item.attempt_id}-${index}`}
                className='break-words text-muted-foreground'
              >
                {metricLabel(item.metric, item.field)}：
                {item.value === null ? '未知' : item.value} · {item.source} ·{' '}
                {item.phase} · {item.complete ? '完整' : '不完整'}
              </p>
            ))
          ) : (
            <p className='text-muted-foreground'>没有确认的原始计量证据</p>
          )}
        </div>
        {(attempt.config_version !== null ||
          attempt.channel_version !== null) && (
          <p className='text-xs text-muted-foreground'>
            模型配置 v{attempt.config_version ?? '—'} · 渠道配置 v
            {attempt.channel_version ?? '—'}
          </p>
        )}
        {(attempt.budget_price ||
          attempt.procurement_price ||
          attempt.budget_estimate ||
          attempt.procurement_estimate) && (
          <CollapsibleSection title='本次尝试的价格与估算快照'>
            <div className='grid gap-2 p-4 text-sm'>
              {attempt.budget_price && (
                <div>
                  <p className='font-medium'>成员预算价</p>
                  <PriceSnapshot price={attempt.budget_price} />
                </div>
              )}
              {attempt.procurement_price && (
                <div>
                  <p className='font-medium'>采购价</p>
                  <PriceSnapshot price={attempt.procurement_price} />
                </div>
              )}
              {attempt.budget_estimate && (
                <p>预算估算：{attempt.budget_estimate}</p>
              )}
              {attempt.procurement_estimate && (
                <p>
                  采购估算：{attempt.procurement_estimate}；不是成员结算金额。
                </p>
              )}
            </div>
          </CollapsibleSection>
        )}
      </CardContent>
    </Card>
  )
}

export function CallDetailSheet({
  id,
  timezone,
  close,
  restoreFocus,
  onAccessDenied,
}: {
  id: string
  timezone: string
  close: () => void
  restoreFocus: () => void
  onAccessDenied: (cause: ApiError) => void
}) {
  const { organization, user } = useOrganization()
  const client = useQueryClient()
  const [reconciling, setReconciling] = useState(false)
  const [childDenied, setChildDenied] = useState<ApiError | null>(null)
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, 'llm-call', id],
    queryFn: ({ signal }) =>
      api<Detail>(`/llm/calls/${id}`, 'GET', undefined, undefined, signal),
  })
  const forbidden =
    query.error instanceof ApiError &&
    [401, 403, 404].includes(query.error.status)
  const detail = forbidden || query.isError || childDenied ? null : query.data
  const call = detail?.call
  const settlement = detail?.settlement
  return (
    <Sheet open onOpenChange={(open) => !open && !reconciling && close()}>
      <SheetContent
        className='w-full sm:max-w-3xl'
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocus()
        }}
      >
        <SheetHeader>
          <SheetTitle>调用详情</SheetTitle>
          <SheetDescription>
            结果与结算是两个独立状态；未知结果不证明客户端已收到内容。
          </SheetDescription>
        </SheetHeader>
        <div className='flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-6'>
          {childDenied ? (
            <RequestError error={childDenied} />
          ) : query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={forbidden ? undefined : () => void query.refetch()}
            />
          ) : (
            detail &&
            call && (
              <>
                <CopyableField
                  label='调用编号'
                  value={call.id}
                  copyLabel='复制调用编号'
                />
                <div className='flex flex-wrap gap-2'>
                  <Badge
                    variant={
                      call.result_status === 'success' ? 'secondary' : 'outline'
                    }
                  >
                    结果：{results[call.result_status]}
                  </Badge>
                  <Badge variant='outline'>
                    结算：{settlements[call.settlement_status]}
                  </Badge>
                </div>
                <div className='grid gap-1 text-sm'>
                  <p>
                    成员 {call.member_name ?? '管理员诊断'} · 模型{' '}
                    {call.model_name ?? '无平台模型'} ·{' '}
                    {operations[call.operation as keyof typeof operations] ??
                      call.operation}
                  </p>
                  <p>
                    来源 {call.source} · 受理{' '}
                    {timeInZone(call.created_at, timezone)} ·{' '}
                    {call.attempt_count} 次尝试
                  </p>
                  <p>
                    总耗时{' '}
                    {call.duration_ms === null
                      ? '未知'
                      : `${call.duration_ms} ms`}{' '}
                    · 终止原因 {call.terminal_reason ?? '未记录'}
                  </p>
                </div>
                {settlement ? (
                  <Card className='min-w-0'>
                    <CardHeader className='pb-2'>
                      <CardTitle size='body'>成员结算</CardTitle>
                    </CardHeader>
                    <CardContent className='grid gap-2 text-sm'>
                      <p>
                        历史预占 {settlement.reserved_points} 积分 · 已结算{' '}
                        {settlement.points ?? '待确认'} 积分
                      </p>
                      {['reserved', 'review'].includes(settlement.status) && (
                        <p>当前占用：{settlement.reserved_points} 积分</p>
                      )}
                      <p>
                        预占金额 {settlement.reserved_amount}{' '}
                        {settlement.currency} · 实际金额{' '}
                        {settlement.amount ?? '待确认'} {settlement.currency}
                      </p>
                      <p>
                        受理时比例 {settlement.ratio} 积分 /{' '}
                        {settlement.currency} · 结算版本 v{settlement.version}
                      </p>
                      {settlement.budget_price && (
                        <div>
                          <p className='font-medium'>受理预算价格快照</p>
                          <PriceSnapshot price={settlement.budget_price} />
                        </div>
                      )}
                      {settlement.policy && (
                        <p>
                          受理策略：{settlement.policy.name ?? '未命名'} · v
                          {settlement.policy.version ?? '—'}
                        </p>
                      )}
                      {settlement.windows.length > 0 && (
                        <CollapsibleSection
                          title={`受理窗口快照 · ${settlement.windows.length} 条`}
                        >
                          <div className='grid gap-2 p-4'>
                            {settlement.windows.map((window, index) => (
                              <p key={index} className='break-words'>
                                {window.kind ?? '窗口'} ·{' '}
                                {window.hours ?? '周周期'} ·{' '}
                                {window.timezone ?? '时区未记录'} · 额度{' '}
                                {window.points ?? '—'} · 当时已用{' '}
                                {window.used ?? '—'} · 当时占用{' '}
                                {window.reserved ?? '—'} · 重置{' '}
                                {window.resets_at
                                  ? timeInZone(window.resets_at, timezone)
                                  : '未记录'}
                              </p>
                            ))}
                          </div>
                        </CollapsibleSection>
                      )}
                      {['review', 'reserved'].includes(settlement.status) && (
                        <Button
                          type='button'
                          variant='outline'
                          className='self-start'
                          onClick={() => setReconciling(true)}
                        >
                          核对用量
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                ) : (
                  <Alert>
                    <AlertTitle>无成员结算</AlertTitle>
                    <AlertDescription>
                      这是管理员诊断，不占成员额度；原始用量只用于诊断证据。
                    </AlertDescription>
                  </Alert>
                )}
                <section className='grid min-w-0 gap-3' aria-label='尝试记录'>
                  <h3 className='font-semibold'>尝试记录</h3>
                  {detail.attempts.length ? (
                    detail.attempts.map((attempt, index) => (
                      <AttemptCard
                        key={attempt.attempt_id ?? index}
                        attempt={attempt}
                      />
                    ))
                  ) : (
                    <p className='text-sm text-muted-foreground'>
                      暂无尝试记录
                    </p>
                  )}
                </section>
                <section className='grid min-w-0 gap-2' aria-label='核对审计'>
                  <h3 className='font-semibold'>核对审计</h3>
                  {detail.audits.length ? (
                    detail.audits.map((audit, index) => (
                      <p
                        key={`${audit.at}-${index}`}
                        className='text-sm break-words text-muted-foreground'
                      >
                        {timeInZone(audit.at, timezone)} ·{' '}
                        {audit.actor_name ?? '管理员'} ·{' '}
                        {audit.reconcile_action === 'settle'
                          ? '结算'
                          : audit.reconcile_action === 'release'
                            ? '释放'
                            : audit.action}{' '}
                        · {audit.result}
                      </p>
                    ))
                  ) : (
                    <p className='text-sm text-muted-foreground'>
                      暂无人工核对记录
                    </p>
                  )}
                </section>
              </>
            )
          )}
        </div>
        {reconciling && settlement && (
          <ReconcileDialog
            callId={id}
            close={() => setReconciling(false)}
            restoreFocus={() => undefined}
            saved={() => {
              setReconciling(false)
              void client.invalidateQueries({
                queryKey: ['organization', organization.tenant_id],
              })
            }}
            onForbidden={(cause) => {
              setChildDenied(cause)
              setReconciling(false)
              onAccessDenied(cause)
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}
