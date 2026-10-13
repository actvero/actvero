import type { Schema } from '@/lib/api'

const labels: Record<
  NonNullable<Schema['ClientEndpoint']['reasons']>[number],
  string
> = {
  operation_not_configured: '未配置此接口',
  model_archived: '模型已归档',
  model_closed: '模型调用已关闭',
  operation_closed: '此接口已关闭',
  no_binding: '尚未关联渠道',
  fixed_target_unset: '未选择固定调用目标',
  binding_closed: '渠道绑定已关闭',
  manual_disabled: '渠道已停用',
  channel_missing: '渠道不存在',
  channel_archived: '渠道已归档',
  source_missing: '上游模型已从渠道移除',
  api_not_declared: '渠道未允许此接口',
  provider_unsupported: '供应商模块未接入此接口',
  credentials_required: '渠道缺少凭据',
  route_unverified: '渠道绑定待验证',
  route_incompatible: '渠道绑定不兼容',
  route_cooldown: '渠道绑定冷却中',
  route_probing: '渠道绑定探测中',
  credential_error: '渠道凭据阻断',
  model_error: '上游模型不可用',
  binding_error: '绑定拒绝待判',
  route_unavailable: '暂无可用调用路径',
  budget_price_missing: '尚未配置预算价格',
}

export function endpointReasonLabel(reason: string): string {
  return labels[reason as keyof typeof labels] ?? '接口状态待确认'
}
