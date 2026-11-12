import { z } from 'zod'
import { departmentGrantSchema } from '@/features/departments/scope'

export const metadataSchema = z
  .object({
    category: z.string().min(1, '请选择类别').max(36).optional(),
    display_name: z.string().trim().min(1, '请输入显示名称').max(100),
    description: z.string().trim().min(1, '请输入简介').max(1024),
    audience: z.enum(['administrators', 'selected', 'organization'], {
      error: '请选择使用范围',
    }),
    member_ids: z.array(z.string()),
    department_grants: z.array(departmentGrantSchema).max(100),
    icon_selection: z
      .object({
        source: z.enum(['auto', 'library', 'upload']),
        key: z.string().optional(),
        image: z.string().optional(),
      })
      .optional(),
  })
  .refine(
    (v) =>
      v.audience !== 'selected' ||
      v.member_ids.length > 0 ||
      v.department_grants.length > 0,
    {
      path: ['member_ids'],
      message: '请至少选择一个部门或成员',
    }
  )
  .transform((values) => ({
    ...values,
    member_ids: values.audience === 'selected' ? values.member_ids : [],
    department_grants:
      values.audience === 'selected' ? values.department_grants : [],
  }))

export type Metadata = z.infer<typeof metadataSchema>
