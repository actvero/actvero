import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Skill = Schema['SkillView']
export type Version = Schema['SkillVersionView']
export type SkillFile = Schema['SkillFile']
export function categoryLabel(skill: Skill) {
  return (
    skill.category_name ??
    (skill.category === 'uncategorized' ? '未分类' : skill.category)
  )
}
export const scopeLabels = {
  administrators: '仅管理员',
  selected: '指定成员',
  organization: '组织全员',
}
export const statusLabels = {
  draft: '草稿',
  published: '生效中',
  superseded: '已替代',
  withdrawn: '已下架',
}
export function sizeLabel(n: number) {
  return n < 1024
    ? `${n} B`
    : n < 1024 * 1024
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1024 / 1024).toFixed(1)} MB`
}
export function useSkills() {
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, 'skills']
  return {
    key,
    csrf,
    refresh: () => client.invalidateQueries({ queryKey: key }),
  }
}
export async function binaryRequest(path: string, csrf: string, body?: Blob) {
  const response = await fetch('/api/v1/skills' + path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'X-CSRF-Token': csrf,
      ...(body ? { 'Content-Type': 'application/zip' } : {}),
    },
    body,
  })
  if (!response.ok) {
    const result = await response.json().catch(() => null)
    throw new ApiError(
      response.status,
      result?.error?.message ?? '请求失败，请稍后重试'
    )
  }
  return response
}
export async function downloadSkill(
  skill: Skill,
  version: Version,
  csrf: string
) {
  const response = await binaryRequest(
    `/${skill.id}/versions/${version.id}/download`,
    csrf
  )
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = `${skill.name}-${version.version}.zip`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function versionAction(
  skill: Skill,
  version: Version,
  action: Schema['SkillAction']['action'],
  csrf: string
) {
  return api<Skill>(
    `/skills/${skill.id}/versions/${version.id}/actions`,
    'POST',
    { action, revision: skill.revision },
    csrf
  )
}
