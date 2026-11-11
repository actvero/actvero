import { useQueryClient } from '@tanstack/react-query'
import type { Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Workbench = Schema['WorkbenchView']
export type WorkbenchSummary = Schema['WorkbenchSummary']
export type WorkbenchVersion = Schema['WorkbenchVersionView']
export type Audience = Schema['WorkbenchScope']['audience']
export type Category = Schema['WorkbenchMetadata']['category']

export const categories: Record<Category, string> = {
  uncategorized: '未分类',
  office: '办公',
  engineering: '研发',
  design: '设计',
  content: '内容',
  data: '数据',
  education: '教育',
  lifestyle: '生活',
  general: '通用',
}

export const audiences: Record<Audience, string> = {
  administrators: '仅管理员',
  organization: '组织全员',
  selected: '指定成员',
}

export const statuses: Record<WorkbenchVersion['status'], string> = {
  draft: '草稿',
  published: '已发布',
  superseded: '已替代',
  withdrawn: '已下架',
}

export const options = (labels: Record<string, string>) =>
  Object.entries(labels).map(([value, label]) => ({ value, label }))

export function packageSize(bytes: number) {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}

export function useWorkbenches() {
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, 'workbenches']
  return {
    key,
    csrf,
    refresh: () => client.invalidateQueries({ queryKey: key }),
    update: (item: Workbench) => {
      client.setQueryData([...key, 'detail', item.id], item)
      void client.invalidateQueries({ queryKey: [...key, 'list'] })
    },
  }
}
