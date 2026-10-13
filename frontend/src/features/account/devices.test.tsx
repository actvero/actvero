import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { DeviceSettings } from './devices'

const device = {
  id: 'test-device',
  name: '测试电脑',
  os: 'macOS',
  app_version: '0.1.0',
  created_at: '2026-09-23T03:00:00Z',
  last_active_at: '2026-09-23T03:00:00Z',
  expires_at: '2026-09-23T11:00:00Z',
  status: 'active',
  current: false,
}
async function screen() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <DeviceSettings userId='test-user' csrf='test-csrf' />
    </QueryClientProvider>
  )
}
afterEach(() => vi.unstubAllGlobals())

describe('桌面登录设备', () => {
  it('空列表不生成示例设备', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(Response.json({ items: [] }))
    )
    const page = await screen()
    await expect.element(page.getByText('尚无桌面登录设备')).toBeVisible()
    expect(page.getByRole('button', { name: /^退出设备 / }).all()).toHaveLength(
      0
    )
  })
  it('取消不撤销，确认携带 CSRF，成功更新状态并恢复焦点', async () => {
    let revoked = false
    const fetcher = vi.fn(async (_url, options) => {
      if (options.method === 'DELETE') {
        revoked = true
        return Response.json({ message: '已退出此设备' })
      }
      return Response.json({
        items: [{ ...device, status: revoked ? 'revoked' : 'active' }],
      })
    })
    vi.stubGlobal('fetch', fetcher)
    const page = await screen()
    const trigger = page.getByRole('button', { name: '退出设备 测试电脑' })
    await userEvent.click(trigger)
    const dialog = page.getByRole('alertdialog', { name: '退出这台设备？' })
    await expect.element(dialog).toBeVisible()
    await userEvent.click(dialog.getByRole('button', { name: '取消' }))
    expect(revoked).toBe(false)
    await expect.element(trigger).toHaveFocus()
    await userEvent.click(trigger)
    await userEvent.click(
      dialog.getByRole('button', { name: '退出设备', exact: true })
    )
    await expect
      .element(page.getByText('已退出', { exact: true }))
      .toBeVisible()
    expect(
      fetcher.mock.calls.some(
        ([url, options]) =>
          url === '/api/v1/account/devices/test-device' &&
          options.method === 'DELETE' &&
          options.headers['X-CSRF-Token'] === 'test-csrf'
      )
    ).toBe(true)
    await expect.element(trigger).toBeDisabled()
    await expect
      .element(page.getByRole('button', { name: '刷新', exact: true }))
      .toHaveFocus()
  })
  it('接口失败保留确认窗口，允许重试', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url, options) =>
        options.method === 'DELETE'
          ? Response.json(
              { error: { message: '暂时无法退出' } },
              { status: 503 }
            )
          : Response.json({ items: [device] })
      )
    )
    const page = await screen()
    await userEvent.click(
      page.getByRole('button', { name: '退出设备 测试电脑' })
    )
    const dialog = page.getByRole('alertdialog')
    await userEvent.click(
      dialog.getByRole('button', { name: '退出设备', exact: true })
    )
    await expect.element(dialog.getByText('暂时无法退出')).toBeVisible()
    await expect
      .element(dialog.getByRole('button', { name: '退出设备', exact: true }))
      .toBeEnabled()
  })
})
