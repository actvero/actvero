import { z } from 'zod'

export const imageSizes = [
  'auto',
  '256x256',
  '512x512',
  '1024x1024',
  '1536x1024',
  '1024x1536',
  '1792x1024',
  '1024x1792',
] as const
export const imageQualities = [
  'auto',
  'low',
  'medium',
  'high',
  'standard',
  'hd',
] as const
export const imageFields = {
  size: z.enum(['', ...imageSizes]),
  quality: z.enum(['', ...imageQualities]),
}
export const imageTestSchema = z.object(imageFields)
export type ImageTestFields = z.infer<typeof imageTestSchema>
