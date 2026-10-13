import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { channelPath } from './api'
import {
  createDiagnosticBatchQueue,
  type DiagnosticBatchQueue,
  type BatchItem,
} from './diagnostic-batch-queue'
import {
  BatchSelection,
  type SelectedBatchItem,
} from './diagnostic-batch-selection'
import { batchInputSummary } from './diagnostic-batch-values'
import { DiagnosticEvidence } from './diagnostic-evidence'
import type { DiagnosticLookup, DiagnosticView } from './diagnostic-request'
import type { Detail } from './shared'
import {
  meterLabel,
  operationLabels,
  type TestOperation,
} from './test-operations'

const allowedOperations: TestOperation[] = ['chat', 'embedding', 'rerank']
const statusLabels: Record<BatchItem['status'], string> = {
  queued: '待发送',
  sending: '执行中',
  success: '成功',
  failure: '失败',
  unknown: '结果未确认',
  stopped: '未发送',
}

function BatchRun({
  queue,
  localBatchId,
  batchVersion,
  currentVersion,
  selected,
  onActiveChange,
  onFinished,
  onRefreshChannel,
  onReset,
}: {
  queue: DiagnosticBatchQueue
  localBatchId: string
  batchVersion: number
  currentVersion: number
  selected: SelectedBatchItem[]
  onActiveChange?: (active: boolean) => void
  onFinished?: () => void
  onRefreshChannel?: () => void
  onReset: () => void
}) {
  const snapshot = useSyncExternalStore(
    queue.subscribe,
    queue.getSnapshot,
    queue.getSnapshot
  )
  const [now, setNow] = useState(0)
  const notified = useRef(false)
  const active = snapshot.state === 'running' || snapshot.state === 'paused'
  useEffect(() => {
    onActiveChange?.(active)
  }, [active, onActiveChange])
  useEffect(() => () => onActiveChange?.(false), [onActiveChange])
  useEffect(() => {
    if (snapshot.state !== 'paused') return
    const tick = () => setNow(Date.now())
    const initial = window.setTimeout(tick, 0)
    const timer = window.setInterval(tick, 1000)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [snapshot.state])
  useEffect(() => {
    if (
      !notified.current &&
      ['done', 'stopped', 'frozen', 'forbidden'].includes(snapshot.state)
    ) {
      notified.current = true
      onFinished?.()
    }
  }, [snapshot.state, onFinished])
  const counts = snapshot.items.reduce(
    (result, item) => {
      result[item.status] += 1
      return result
    },
    { queued: 0, sending: 0, success: 0, failure: 0, unknown: 0, stopped: 0 }
  )
  const completed = snapshot.items.length - counts.queued - counts.sending
  const resumed = snapshot.resumeAt === null || now >= snapshot.resumeAt
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <p className='text-sm break-all text-muted-foreground'>
        本地批次号：{localBatchId}（仅本页） · 启动时渠道配置 v{batchVersion}
      </p>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge
          variant={
            snapshot.state === 'done' && !counts.failure && !counts.unknown
              ? 'success'
              : 'outline'
          }
        >
          {snapshot.state === 'running'
            ? '批量执行中'
            : snapshot.state === 'paused'
              ? '已暂停'
              : snapshot.state === 'frozen'
                ? '配置变化，已冻结'
                : snapshot.state === 'forbidden'
                  ? '权限已失效'
                  : snapshot.state === 'stopped'
                    ? '已停止'
                    : '批量已结束'}
        </Badge>
        <span className='text-sm'>
          完成 {completed}/{snapshot.items.length} · 成功 {counts.success} ·
          失败 {counts.failure} · 未确认 {counts.unknown} · 未发送{' '}
          {counts.stopped + counts.queued}
        </span>
      </div>
      {snapshot.state === 'paused' && (
        <p className='text-sm'>
          服务端限流：{snapshot.reason ?? '稍后继续'}。
          {snapshot.resumeAt
            ? `可在 ${new Date(snapshot.resumeAt).toLocaleString('zh-CN', { hour12: false })} 后明确继续。`
            : ''}
          失败项不会重发。
        </p>
      )}
      {snapshot.state === 'running' && snapshot.localWaitUntil !== null && (
        <p className='text-sm'>
          本地 10/60 限速窗口已满，预计在{' '}
          {new Date(snapshot.localWaitUntil).toLocaleString('zh-CN', {
            hour12: false,
          })}{' '}
          自动继续未发送项；服务端 429 则会另行暂停并要求明确继续。
        </p>
      )}
      {snapshot.refreshRequired && snapshot.state !== 'forbidden' && (
        <p className='text-sm'>
          配置已变化；已停止派发。请按原请求号核对已发项，刷新渠道后再建新批次。
        </p>
      )}
      {snapshot.refreshRequired && currentVersion === batchVersion && (
        <p className='text-sm'>
          当前仍显示启动时的渠道版本；请关闭并重新打开详情或刷新渠道配置。
        </p>
      )}
      {snapshot.state === 'forbidden' ? (
        <p className='text-sm'>
          权限已失效，结果已从当前视图清除；不能继续派发或回查。
        </p>
      ) : (
        <>
          <div className='flex flex-wrap gap-2'>
            {snapshot.refreshRequired && onRefreshChannel && (
              <Button
                type='button'
                variant='outline'
                onClick={onRefreshChannel}
              >
                刷新渠道配置
              </Button>
            )}
            {snapshot.state === 'paused' && (
              <Button
                type='button'
                disabled={!resumed}
                onClick={() => queue.resume()}
              >
                明确继续未发送项
              </Button>
            )}
            {['running', 'paused', 'frozen'].includes(snapshot.state) && (
              <Button
                type='button'
                variant='outline'
                onClick={() => queue.stop()}
              >
                停止派发与等待
              </Button>
            )}
            {['done', 'stopped', 'frozen'].includes(snapshot.state) && (
              <Button
                type='button'
                variant='outline'
                disabled={
                  snapshot.refreshRequired && currentVersion === batchVersion
                }
                onClick={onReset}
              >
                配置新批次
              </Button>
            )}
          </div>
          {counts.success > 0 &&
            (counts.failure > 0 ||
              counts.unknown > 0 ||
              counts.stopped > 0) && (
              <p className='text-sm'>
                本批部分成功；失败与未确认项不会自动重发。
              </p>
            )}
          <div
            className='flex min-w-0 flex-col gap-3'
            aria-label='批量诊断进度'
          >
            {snapshot.items.map((item) => {
              const source = selected[item.index]
              const attempt =
                item.record?.record.attempt ?? item.result?.attempt
              const certification =
                item.record?.record.health_certification ??
                item.result?.health_certification
              return (
                <div
                  key={item.index}
                  className='flex min-w-0 flex-col gap-2 rounded-md border p-3 text-sm'
                >
                  <div className='flex min-w-0 flex-wrap items-center justify-between gap-2'>
                    <strong className='min-w-0 break-all'>
                      {item.index + 1}. {item.modelId} ·{' '}
                      {operationLabels[item.operation]}
                    </strong>
                    <Badge
                      variant={
                        item.status === 'success'
                          ? 'success'
                          : item.status === 'failure'
                            ? 'destructive'
                            : 'outline'
                      }
                    >
                      {statusLabels[item.status]}
                    </Badge>
                  </div>
                  {source && (
                    <p className='text-muted-foreground'>
                      {batchInputSummary(source.values)}
                    </p>
                  )}
                  {item.requestId && (
                    <p className='break-all text-muted-foreground'>
                      请求号：{item.requestId}
                    </p>
                  )}
                  {item.error && <p>{item.error}</p>}
                  {item.result && (
                    <>
                      <p>
                        {item.result.message} · {item.result.duration_ms} ms
                      </p>
                      <p className='text-muted-foreground'>
                        {item.result.usage_source === 'upstream'
                          ? `上游原始用量：${meterLabel(item.operation, item.result)}`
                          : '上游未返回完整用量，未补零'}
                      </p>
                      {item.result.output && (
                        <Textarea
                          aria-label={`${item.modelId} 返回内容`}
                          readOnly
                          value={item.result.output}
                          rows={3}
                        />
                      )}
                      {!!item.result.vectors?.length && (
                        <p>
                          返回 {item.result.vectors.length}{' '}
                          条向量（详情仅在本次内存可见）
                        </p>
                      )}
                      {!!item.result.ranks?.length && (
                        <p>
                          返回 {item.result.ranks.length}{' '}
                          条重排结果（详情仅在本次内存可见）
                        </p>
                      )}
                    </>
                  )}
                  {item.record && <p>已按原请求号回查；正文与媒体不可恢复。</p>}
                  {attempt && (
                    <DiagnosticEvidence
                      attempt={attempt}
                      healthCertification={certification}
                    />
                  )}
                  {item.requestId && item.status !== 'sending' && (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      className='self-start'
                      onClick={() => void queue.readRecord(item.index)}
                    >
                      按原请求号回查
                    </Button>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export function ChannelDiagnosticBatch({
  channel,
  operations,
  onActiveChange,
  onFinished,
  onRefreshChannel,
}: {
  channel: Detail
  operations: TestOperation[]
  onActiveChange?: (active: boolean) => void
  onFinished?: () => void
  onRefreshChannel?: () => void
}) {
  const { csrf } = useOrganization()
  const [selectionOpen, setSelectionOpen] = useState(false)
  const [selected, setSelected] = useState<SelectedBatchItem[]>([])
  const [queue, setQueue] = useState<DiagnosticBatchQueue | null>(null)
  const [localBatchId, setLocalBatchId] = useState('')
  const [batchVersion, setBatchVersion] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const permitted = allowedOperations.filter((operation) =>
    operations.includes(operation)
  )
  useEffect(() => () => queue?.dispose(), [queue])
  function start() {
    if (queue || channel.archived || !selected.length) return
    try {
      const instance = createDiagnosticBatchQueue({
        channel,
        items: selected.map((item) => item.values),
        send: (body, signal) =>
          api<DiagnosticView>(
            channelPath(channel.id) + '/diagnostics',
            'POST',
            body,
            csrf,
            signal
          ),
        lookup: (requestId, signal) =>
          api<DiagnosticLookup>(
            `/llm/diagnostics/${requestId}`,
            'GET',
            undefined,
            undefined,
            signal
          ),
      })
      setError(null)
      setLocalBatchId(crypto.randomUUID())
      setBatchVersion(channel.version)
      setQueue(instance)
      instance.start()
    } catch (cause) {
      setError(cause)
    }
  }
  if (!queue && (!channel.models.length || !permitted.length))
    return (
      <p className='text-sm text-muted-foreground'>
        当前渠道没有已登记模型或可用的批量诊断操作。
      </p>
    )
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <p className='text-sm text-muted-foreground'>
        仅普通非流式对话、向量和重排；最多 50 项，同时最多 2 项。每位管理员每 60
        秒最多受理 10
        项，达到限制后按服务端等待时间暂停。可能产生上游费用，不扣成员额度。
      </p>
      {!queue ? (
        <>
          <div className='flex flex-wrap items-center gap-2'>
            <Button
              type='button'
              variant='outline'
              disabled={channel.archived}
              onClick={() => setSelectionOpen(true)}
            >
              选择已登记模型／操作
            </Button>
            <span className='text-sm'>已选 {selected.length}/50</span>
          </div>
          {selected.map((item) => (
            <div
              key={item.key}
              className='min-w-0 rounded-md border p-3 text-sm'
            >
              <strong className='break-all'>
                {item.values.id} ·{' '}
                {operationLabels[item.values.operation as TestOperation]}
              </strong>
              <p className='text-muted-foreground'>
                {batchInputSummary(item.values)}
              </p>
            </div>
          ))}
          <Button
            type='button'
            className='self-start'
            disabled={channel.archived || !selected.length}
            onClick={start}
          >
            开始批量诊断
          </Button>
        </>
      ) : (
        <BatchRun
          queue={queue}
          localBatchId={localBatchId}
          batchVersion={batchVersion ?? channel.version}
          currentVersion={channel.version}
          selected={selected}
          onActiveChange={onActiveChange}
          onFinished={onFinished}
          onRefreshChannel={onRefreshChannel}
          onReset={() => {
            queue.dispose()
            setQueue(null)
            setLocalBatchId('')
            setBatchVersion(null)
            setSelected([])
            setError(null)
          }}
        />
      )}
      {!!error && <RequestError error={error} />}
      {selectionOpen && (
        <BatchSelection
          channel={channel}
          operations={permitted}
          selected={selected}
          onCancel={() => setSelectionOpen(false)}
          onConfirm={(items) => {
            setSelected(items)
            setSelectionOpen(false)
            setError(null)
          }}
        />
      )}
    </div>
  )
}
