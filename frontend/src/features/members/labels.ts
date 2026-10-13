export const roles = { administrator: '管理员', member: '普通成员' } as const
export const states: Record<string, string> = {
  active: '正常',
  paused: '已暂停',
  removed: '已移除',
  pending: '待接受',
  accepted: '已加入',
  expired: '已过期',
  revoked: '已撤销',
  submitted: '已提交',
  failed: '发送失败',
}
export const roleOptions = Object.entries(roles).map(([value, label]) => ({
  value,
  label,
}))
export function roleName(role: string) {
  return roles[role as keyof typeof roles] ?? role
}
