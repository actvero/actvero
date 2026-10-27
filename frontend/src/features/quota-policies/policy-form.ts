import { z } from 'zod'
import type { Schema } from '@/lib/api'

export type Policy = Schema['QuotaPolicyView']
export type QuotaRule = Policy['rules'][number]
export const timezones = [
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'Asia/Singapore',
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'America/New_York',
  'America/Los_Angeles',
]
const points = z
  .string()
  .regex(
    /^(0|[1-9][0-9]{0,17})(\.[0-9]{1,12})?$/,
    '填写非负积分，最多 12 位小数'
  )
const integer = (min: number, max: number) =>
  z
    .string()
    .refine(
      (v) => /^\d+$/.test(v) && Number(v) >= min && Number(v) <= max,
      `填写 ${min}–${max} 的整数`
    )
export const policySchema = z
  .object({
    name: z.string().trim().min(1, '填写策略名称').max(100, '最多 100 字'),
    is_default: z.boolean(),
    mode: z.enum(['limited', 'unlimited']),
    rules: z
      .array(
        z.object({
          kind: z.literal('fixed_hours'),
          points: z.string(),
          hours: z.string(),
        })
      )
      .max(10),
  })
  .superRefine((v, ctx) => {
    if (v.mode === 'unlimited') return
    if (!v.rules.length)
      ctx.addIssue({
        code: 'custom',
        path: ['rules'],
        message: '至少添加一条额度规则',
      })
    const seen = new Set<string>()
    v.rules.forEach((r, index) => {
      if (!points.safeParse(r.points).success)
        ctx.addIssue({
          code: 'custom',
          path: ['rules', index, 'points'],
          message: '填写非负积分，最多 12 位小数',
        })
      const key = `hours-${Number(r.hours)}`
      if (seen.has(key))
        ctx.addIssue({
          code: 'custom',
          path: ['rules', index, 'points'],
          message: '这个周期已配置额度',
        })
      seen.add(key)
      if (
        r.kind === 'fixed_hours' &&
        !integer(1, 720).safeParse(r.hours).success
      )
        ctx.addIssue({
          code: 'custom',
          path: ['rules', index, 'hours'],
          message: '填写 1–720 小时',
        })
    })
  })
export type PolicyValues = z.infer<typeof policySchema>
export const newRule = (
  kind: QuotaRule['kind']
): PolicyValues['rules'][number] => ({
  kind,
  hours: '',
  points: '',
})
export function values(policy?: Policy, isDefault = false): PolicyValues {
  return {
    name: policy?.name ?? (isDefault ? '默认' : ''),
    is_default: policy?.is_default ?? isDefault,
    mode: policy?.mode ?? 'limited',
    rules: policy
      ? policy.rules.map((r) => ({
          ...newRule(r.kind),
          points: r.points,
          hours: String(r.hours),
        }))
      : [newRule('fixed_hours')],
  }
}
export function policyInput(v: PolicyValues): Schema['QuotaPolicyInput'] {
  return {
    name: v.name,
    is_default: v.is_default,
    mode: v.mode,
    rules:
      v.mode === 'unlimited'
        ? []
        : v.rules.map((r) => ({
            kind: r.kind,
            hours: Number(r.hours),
            points: r.points,
          })),
  }
}
export function ruleLabel(r: QuotaRule) {
  return `${r.hours} 小时 · ${r.points} 积分`
}
