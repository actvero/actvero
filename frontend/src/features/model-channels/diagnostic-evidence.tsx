import type { Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

type Attempt = NonNullable<Schema['ChannelTestView']['attempt']>
const usageLabels: Record<string, string> = {
  input_tokens: '输入 Token',
  output_tokens: '输出 Token',
  cache_read_tokens: '缓存读取 Token',
  cache_write_5m_tokens: '5 分钟缓存写入 Token',
  cache_write_1h_tokens: '1 小时缓存写入 Token',
  search_units: '搜索单位',
  image_count: '图片张数',
  input_characters: '输入字符数',
  raw_prompt_tokens: '上游提示 Token',
  raw_completion_tokens: '上游完成 Token',
  raw_input_tokens: '上游输入 Token',
  raw_output_tokens: '上游输出 Token',
  raw_prompt_token_count: '上游提示 Token',
  raw_candidates_token_count: '上游候选 Token',
  raw_thoughts_token_count: '上游思考 Token',
}
const sourceLabels: Record<string, string> = {
  upstream: '上游原始',
  validated_input: '已校验输入',
  confirmed_delivery: '已确认交付',
  unknown: '来源未确认',
}

function flag(value: unknown, yes: string, no: string, unknown: string) {
  return value === true ? yes : value === false ? no : unknown
}

export function DiagnosticEvidence({
  attempt,
  healthCertification,
}: {
  attempt?: Attempt | null
  healthCertification?: 'not_requested' | 'certified' | 'not_certified' | null
}) {
  if (!attempt && !healthCertification) return null
  const usage = Array.isArray(attempt?.usage_evidence)
    ? attempt.usage_evidence.filter(
        (item): item is Record<string, unknown> =>
          !!item && typeof item === 'object' && !Array.isArray(item)
      )
    : []
  const visibleUsage = usage.filter(
    (item) =>
      typeof item.field === 'string' &&
      item.field in usageLabels &&
      (typeof item.value === 'number' || item.value === null)
  )
  const completeUsage = visibleUsage.filter((item) => item.complete === true)
  return (
    <div className='flex min-w-0 flex-col gap-2 text-sm' aria-label='执行证据'>
      <div className='flex flex-wrap items-center gap-2'>
        <strong>执行证据</strong>
        {healthCertification && healthCertification !== 'not_requested' && (
          <Badge
            variant={
              healthCertification === 'certified' ? 'success' : 'outline'
            }
          >
            {healthCertification === 'certified'
              ? '绑定健康已认证'
              : '绑定健康未认证'}
          </Badge>
        )}
      </div>
      {attempt ? (
        <>
          <div className='grid gap-1 text-muted-foreground sm:grid-cols-2'>
            <span>
              发送：{flag(attempt.sent, '已发送', '未发送', '未确认')}
            </span>
            <span>
              首输出：
              {flag(attempt.output_started, '已产生', '未产生', '未确认')}
            </span>
            <span>
              上游终态：
              {flag(attempt.upstream_terminal, '已观察', '未观察', '未确认')}
            </span>
            <span>
              客户端交付：
              {flag(attempt.client_terminal, '已确认', '未完成', '未确认')}
            </span>
            <span>
              完整用量证据：
              {completeUsage.length ? `${completeUsage.length} 项` : '未返回'}
            </span>
            {typeof attempt.first_output_ms === 'number' && (
              <span>首输出时间：{attempt.first_output_ms} ms</span>
            )}
          </div>
          {!!visibleUsage.length && (
            <ul className='flex flex-col gap-1 text-muted-foreground'>
              {visibleUsage.map((item, index) => (
                <li key={`${item.field}-${item.phase}-${index}`}>
                  {usageLabels[String(item.field)]}：
                  {typeof item.value === 'number' ? item.value : '未知'} ·{' '}
                  {sourceLabels[String(item.source)] ?? '来源未确认'} ·{' '}
                  {item.complete === true ? '完整' : '不完整'}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className='text-muted-foreground'>这条旧记录没有逐次执行证据。</p>
      )}
      {attempt?.uncertain === true && (
        <p>执行结果未确认；请求可能已发送并产生上游费用。</p>
      )}
    </div>
  )
}
