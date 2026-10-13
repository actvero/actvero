import { ApiError, type Schema } from '@/lib/api'

export async function uploadAvatar(
  file: File,
  csrf: string
): Promise<Schema['UserView']> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type))
    throw new Error('请选择 PNG、JPG 或 WebP 图片')
  if (file.size > 2 * 1024 * 1024) throw new Error('头像文件不能超过 2 MB')
  const response = await fetch('/api/v1/account/avatar', {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': file.type, 'X-CSRF-Token': csrf },
    body: file,
  })
  const result = await response.json().catch(() => null)
  if (!response.ok)
    throw new ApiError(
      response.status,
      result?.error?.message ?? '头像上传失败，请重试'
    )
  return result as Schema['UserView']
}
