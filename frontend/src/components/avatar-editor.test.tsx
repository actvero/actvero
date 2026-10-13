import '@/styles/index.css'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { AvatarEditor } from './avatar-editor'

async function sampleImage() {
  const canvas = document.createElement('canvas')
  canvas.width = 300
  canvas.height = 200
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ff0000'
  ctx.fillRect(0, 0, 300, 200)
  ctx.fillStyle = '#00ff00'
  ctx.fillRect(100, 0, 100, 200)
  const blob = await new Promise<Blob>((resolve) =>
    canvas.toBlob((value) => resolve(value!), 'image/png')
  )
  return new File([blob], 'test-avatar.png', { type: 'image/png' })
}

afterEach(() => vi.restoreAllMocks())

describe('共享头像编辑器', () => {
  it('选图、缩放后才提交裁剪图，输出固定尺寸且不包含原始边缘', async () => {
    const onChange = vi
      .fn<(file: File | null) => Promise<void>>()
      .mockResolvedValue()
    const page = await render(
      <AvatarEditor fallback='用户' onChange={onChange} />
    )
    await expect.element(page.getByRole('menuitem')).not.toBeInTheDocument()
    await userEvent.click(page.getByRole('button', { name: '编辑头像' }))
    await expect.element(page.getByRole('menu')).toBeVisible()
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    await expect
      .element(page.getByRole('menuitem', { name: '移除' }))
      .toHaveAttribute('aria-disabled', 'true')
    const pickFile = vi
      .spyOn(
        page.getByLabelText('选择头像').element() as HTMLInputElement,
        'click'
      )
      .mockImplementation(() => {})
    await userEvent.click(page.getByRole('menuitem', { name: '更换' }))
    expect(pickFile).toHaveBeenCalledOnce()
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    await userEvent.upload(page.getByLabelText('选择头像'), await sampleImage())
    await expect.element(page.getByRole('menu')).not.toBeInTheDocument()
    await expect
      .poll(() =>
        page.getByRole('dialog').element().contains(document.activeElement)
      )
      .toBe(true)
    await expect
      .element(page.getByRole('button', { name: '应用裁剪' }))
      .toBeEnabled()
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.click(page.getByRole('slider', { name: '缩放' }))
    await userEvent.keyboard('{End}')
    await expect.element(page.getByText('300%')).toBeVisible()
    await userEvent.click(page.getByRole('button', { name: '应用裁剪' }))
    await expect.poll(() => onChange.mock.calls.length).toBe(1)
    const file = onChange.mock.calls[0][0]!
    expect(file.type).toBe('image/webp')
    expect(file.size).toBeLessThan(256 * 1024)
    const bitmap = await createImageBitmap(file)
    expect([bitmap.width, bitmap.height]).toEqual([256, 256])
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 256
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(bitmap, 0, 0)
    const [red, green] = ctx.getImageData(5, 128, 1, 1).data
    expect(green).toBeGreaterThan(240)
    expect(red).toBeLessThan(15)
    bitmap.close()
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    await expect
      .element(page.getByRole('button', { name: '编辑头像', exact: true }))
      .toHaveFocus()
  })
  it('已有头像先打开操作菜单，移除失败可重试，处理中防止关闭和重复操作', async () => {
    let fail!: (reason: Error) => void
    const onChange = vi
      .fn<(file: File | null) => Promise<void>>()
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            fail = reject
          })
      )
      .mockResolvedValue()
    const value = URL.createObjectURL(await sampleImage())
    try {
      const page = await render(
        <AvatarEditor value={value} fallback='用户' onChange={onChange} />
      )
      const trigger = page.getByRole('button', { name: '编辑头像' })
      trigger.element().focus()
      await userEvent.keyboard('{Enter}')
      await expect
        .element(page.getByRole('menuitem', { name: '更换' }))
        .toHaveFocus()
      await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
      expect(onChange).not.toHaveBeenCalled()
      await userEvent.keyboard('{Escape}')
      await expect.element(trigger).toHaveFocus()
      await userEvent.click(trigger)
      await userEvent.click(
        page.getByRole('menuitem', { name: '移除', exact: true })
      )
      expect(onChange).toHaveBeenCalledExactlyOnceWith(null)
      await expect
        .element(page.getByRole('menuitem', { name: '移除中…' }))
        .toHaveAttribute('aria-disabled', 'true')
      await expect
        .element(page.getByRole('menuitem', { name: '更换' }))
        .toHaveAttribute('aria-disabled', 'true')
      await userEvent.keyboard('{Escape}')
      await expect.element(page.getByRole('menu')).toBeVisible()
      fail(new Error('移除失败，请重试'))
      await expect.element(page.getByText('移除失败，请重试')).toBeVisible()
      await userEvent.click(
        page.getByRole('menuitem', { name: '移除', exact: true })
      )
      await expect.element(page.getByRole('menu')).not.toBeInTheDocument()
      expect(onChange).toHaveBeenCalledTimes(2)
      await expect.element(trigger).toHaveFocus()
    } finally {
      URL.revokeObjectURL(value)
    }
  })
  it('超大文件留在操作菜单提示错误，不进入裁切', async () => {
    const onChange = vi.fn()
    const page = await render(
      <AvatarEditor fallback='用户' onChange={onChange} />
    )
    await userEvent.click(page.getByRole('button', { name: '编辑头像' }))
    await userEvent.upload(
      page.getByLabelText('选择头像'),
      new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'large.png', {
        type: 'image/png',
      })
    )
    await expect
      .element(page.getByText('请选择不超过 2 MB 的 PNG、JPG 或 WebP 图片'))
      .toBeVisible()
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    await expect
      .element(page.getByRole('button', { name: '编辑头像' }))
      .toHaveFocus()
  })
  it('取消裁剪不上传，原图可再次选择；无效格式给出错误', async () => {
    const onChange = vi.fn()
    const page = await render(
      <AvatarEditor fallback='用户' onChange={onChange} />
    )
    const file = await sampleImage()
    await userEvent.upload(page.getByLabelText('选择头像'), file)
    await expect.element(page.getByRole('dialog')).toBeVisible()
    await userEvent.click(
      page.getByRole('button', { name: '取消', exact: true })
    )
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.upload(page.getByLabelText('选择头像'), file)
    await expect
      .element(page.getByRole('button', { name: '应用裁剪' }))
      .toBeEnabled()
    await userEvent.keyboard('{Escape}')
    await userEvent.upload(
      page.getByLabelText('选择头像'),
      new File(['invalid'], 'test.png', { type: 'image/png' })
    )
    await expect
      .element(page.getByText('图片无法读取，请重新选择'))
      .toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '应用裁剪' }))
      .toBeDisabled()
    expect(onChange).not.toHaveBeenCalled()
  })
  it('保存失败保留裁剪结果，可重试；处理中不允许重复提交', async () => {
    let fail!: (reason: Error) => void
    const onChange = vi
      .fn<(file: File | null) => Promise<void>>()
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            fail = reject
          })
      )
      .mockResolvedValue()
    const page = await render(
      <AvatarEditor fallback='用户' label='连接器图标' onChange={onChange} />
    )
    await userEvent.upload(
      page.getByLabelText('选择连接器图标'),
      await sampleImage()
    )
    await expect
      .element(page.getByRole('button', { name: '应用裁剪' }))
      .toBeEnabled()
    await userEvent.click(page.getByRole('button', { name: '应用裁剪' }))
    await expect.poll(() => onChange.mock.calls.length).toBe(1)
    await expect
      .element(page.getByRole('button', { name: '处理中…' }))
      .toBeDisabled()
    await userEvent.keyboard('{Escape}')
    await expect.element(page.getByRole('dialog')).toBeVisible()
    fail(new Error('保存失败，请重试'))
    await expect.element(page.getByText('保存失败，请重试')).toBeVisible()
    await userEvent.click(page.getByRole('button', { name: '应用裁剪' }))
    await expect.poll(() => onChange.mock.calls.length).toBe(2)
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
  })
})
