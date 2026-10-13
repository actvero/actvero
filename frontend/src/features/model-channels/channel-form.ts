import { z } from 'zod'

export const modelIds = (value: string) => [
  ...new Set(
    value
      .split(/[\n,，]/)
      .map((id) => id.trim())
      .filter(Boolean)
  ),
]
export const validModelId = (id: string) =>
  /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/.test(id)
const safeAddress = (value: string) => {
  try {
    const url = new URL(value)
    return (
      ['https:', 'http:'].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    )
  } catch {
    return false
  }
}
export const channelSchema = z
  .object({
    name: z.string().trim().min(1, '请输入渠道名称').max(100),
    description: z.string().trim().max(500),
    icon: z.string(),
    address_mode: z.enum([
      'provider_default',
      'service_root',
      'legacy_api_base',
    ]),
    base_url: z.string().trim(),
    service_root: z.string().trim(),
    custom_prefix: z.boolean(),
    api_prefix: z
      .string()
      .trim()
      .refine(
        (value) =>
          !value ||
          (value.startsWith('/') &&
            !value.startsWith('//') &&
            !/[?#]/.test(value)),
        '接口前缀须是以 / 开头的同源相对路径'
      ),
    auth_mode: z.enum(['api_key', 'none']),
    api_key: z
      .string()
      .max(4096)
      .refine(
        (value) => !value || /^[!-~]+$/.test(value),
        'API Key 不能包含空白或不可打印字符'
      ),
    timeout_seconds: z.number().int().min(3, '至少 3 秒').max(60, '最多 60 秒'),
    declared_apis: z.array(
      z.enum([
        'chat_completions',
        'responses',
        'embeddings',
        'rerank',
        'images',
      ])
    ),
    manual_enabled: z.boolean(),
    automatic_protection: z.boolean(),
    test_upstream_id: z.string(),
    test_operation: z.enum([
      '',
      'chat',
      'embedding',
      'rerank',
      'image_generation',
      'speech',
    ]),
    test_stream: z.boolean(),
    models: z
      .array(z.string().refine(validModelId, '模型 ID 格式不正确'))
      .max(1000, '每个渠道最多登记 1000 个模型'),
    manual_models: z
      .string()
      .refine(
        (value) => modelIds(value).every(validModelId),
        '模型 ID 最多 200 个字符，支持字母、数字和 . _ : / @ + -'
      ),
  })
  .superRefine((values, context) => {
    const address =
      values.address_mode === 'service_root'
        ? values.service_root
        : values.base_url
    if (values.address_mode !== 'provider_default' && !safeAddress(address)) {
      context.addIssue({
        code: 'custom',
        path: [
          values.address_mode === 'service_root' ? 'service_root' : 'base_url',
        ],
        message: '请输入不含账号、查询参数或片段的完整 HTTP(S) 地址',
      })
    }
  })
export type ChannelValues = z.infer<typeof channelSchema>
