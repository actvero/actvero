import { z } from 'zod'

export const metadataSchema = z
  .object({
    category: z.string().min(1, '请选择类别').max(36).optional(),
    display_name: z.string().trim().min(1, '请输入显示名称').max(100),
    description: z.string().trim().min(1, '请输入简介').max(1024),
    audience: z.enum(['administrators', 'selected', 'organization'], {
      error: '请选择使用范围',
    }),
    member_ids: z.array(z.string()),
    icon_selection: z
      .object({
        source: z.enum(['auto', 'library', 'upload']),
        key: z.string().optional(),
        image: z.string().optional(),
      })
      .optional(),
  })
  .refine((v) => v.audience !== 'selected' || v.member_ids.length > 0, {
    path: ['member_ids'],
    message: '请至少选择一名成员',
  })
  .transform((values) => ({
    ...values,
    member_ids: values.audience === 'selected' ? values.member_ids : [],
  }))

export type Metadata = z.infer<typeof metadataSchema>
