import { z } from 'zod'
import type { Schema } from '@/lib/api'

export type Policy = Schema['QuotaPolicyView']
export type QuotaRule = Policy['rules'][number]
export const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
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
    priority: integer(0, 1000000),
    member_ids: z.array(z.string()).max(1000),
    rules: z
      .array(
        z.object({
          kind: z.enum(['fixed_hours', 'calendar_week']),
          points,
          hours: z.string(),
          timezone: z.string(),
          week_start: z.string(),
        })
      )
      .min(1, '至少添加一条额度规则')
      .max(10),
  })
  .superRefine((v, ctx) => {
    if (Number(v.priority) > 0 && !v.member_ids.length)
      ctx.addIssue({
        code: 'custom',
        path: ['member_ids'],
        message: '至少选择一名成员',
      })
    const seen = new Set<string>()
    v.rules.forEach((r, index) => {
      const key = r.kind === 'fixed_hours' ? `hours-${Number(r.hours)}` : 'week'
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
      if (r.kind === 'calendar_week') {
        if (!/^[0-6]$/.test(r.week_start))
          ctx.addIssue({
            code: 'custom',
            path: ['rules', index, 'week_start'],
            message: '选择周起始日',
          })
        if (!r.timezone)
          ctx.addIssue({
            code: 'custom',
            path: ['rules', index, 'timezone'],
            message: '选择时区',
          })
      }
    })
  })
export type PolicyValues = z.infer<typeof policySchema>
export const newRule = (
  kind: QuotaRule['kind']
): PolicyValues['rules'][number] => ({
  kind,
  hours: '',
  points: '',
  timezone: '',
  week_start: '',
})
export function values(policy?: Policy, isDefault = false): PolicyValues {
  return {
    name: policy?.name ?? (isDefault ? '默认' : ''),
    priority: policy ? String(policy.priority) : isDefault ? '0' : '',
    member_ids: policy?.member_ids ?? [],
    rules: policy
      ? policy.rules.map((r) => ({
          ...newRule(r.kind),
          points: r.points,
          ...(r.kind === 'fixed_hours'
            ? { hours: String(r.hours) }
            : { timezone: r.timezone, week_start: String(r.week_start) }),
        }))
      : [newRule('fixed_hours')],
  }
}
export function policyInput(v: PolicyValues): Schema['QuotaPolicyInput'] {
  return {
    name: v.name,
    priority: Number(v.priority),
    member_ids: Number(v.priority) === 0 ? [] : v.member_ids,
    rules: v.rules.map((r) =>
      r.kind === 'fixed_hours'
        ? { kind: r.kind, hours: Number(r.hours), points: r.points }
        : {
            kind: r.kind,
            points: r.points,
            timezone: r.timezone,
            week_start: Number(r.week_start),
          }
    ),
  }
}
export function ruleLabel(r: QuotaRule) {
  return `${r.kind === 'fixed_hours' ? `${r.hours} 小时` : '每周'} · ${r.points} 积分`
}
