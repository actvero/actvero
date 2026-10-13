import type { Schema } from '@/lib/api'

export const channelPath = (id: string) => `/llm/channels/${id}`

export const healthLabels: Record<
  Schema['ChannelHealthSummary']['state'],
  string
> = {
  not_applicable: '不适用（已归档）',
  no_routes: '未关联可调用模型',
  ready: '就绪',
  degraded: '部分异常',
  unavailable: '暂无可用绑定',
  unverified: '待验证',
}
