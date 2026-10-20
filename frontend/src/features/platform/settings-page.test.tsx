import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { BrandHead, BrandLockup } from '@/features/branding/brand'
import { OrganizationInvitationsPage } from './invitations-page'
import { PlatformMailPage } from './mail-page'
import { MailSettingsForm } from './mail-settings-form'
import { PlatformMailTemplatesPage } from './mail-templates-page'
import { PlatformGeneralSettingsPage } from './settings-page'

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({
    data: { csrf: 'test-csrf', user: { email: 'operator@example.com' } },
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    children,
    action,
  }: {
    title: string
    children: ReactNode
    action?: ReactNode
  }) => (
    <main>
      <h1>{title}</h1>
      {action}
      {children}
    </main>
  ),
}))

const mail = {
  enabled: true,
  source: 'platform' as const,
  host: 'smtp.example.com',
  port: 465,
  security: 'tls' as const,
  username: 'operator@example.com',
  sender: 'operator@example.com',
  password_set: true,
}
function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
  return client
}
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const brand = {
  name: 'Example Platform',
  revision: 'brand-v1',
  assets: {},
  asset_ids: {},
  favicon_url: '/favicon.ico',
  apple_icon_url: '/brand/actvero-icon.png',
  identity_status: 'applied' as const,
}

async function wordmarkFile() {
  const canvas = document.createElement('canvas')
  canvas.width = 600
  canvas.height = 150
  canvas.getContext('2d')!.fillRect(0, 0, 600, 150)
  const blob = await new Promise<Blob>((resolve) =>
    canvas.toBlob((value) => resolve(value!), 'image/png')
  )
  return new File([blob], 'wordmark.png', { type: 'image/png' })
}

it('previews uploads without publishing and cancels the entire draft', async () => {
  const writes = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') writes()
      return response(brand)
    })
  )
  mount(<PlatformGeneralSettingsPage />)
  await page.getByRole('textbox', { name: '平台名称' }).fill('草稿品牌')
  await userEvent.upload(
    page.getByLabelText('横版 Logo · 浅色背景（可选）'),
    await wordmarkFile()
  )
  await expect.element(page.getByText('600 × 150 · 保存后应用')).toBeVisible()
  const preview = page
    .getByRole('img', { name: '横版 Logo · 浅色背景（可选）' })
    .element() as HTMLImageElement
  expect(preview.naturalWidth / preview.naturalHeight).toBe(4)
  expect(getComputedStyle(preview).objectFit).toBe('contain')
  expect(writes).not.toHaveBeenCalled()
  await page.getByRole('button', { name: '取消更改', exact: true }).click()
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toHaveValue('Example Platform')
  await expect
    .element(page.getByText('600 × 150 · 保存后应用'))
    .not.toBeInTheDocument()
  expect(writes).not.toHaveBeenCalled()
})

it('publishes name and assets together and updates the browser title and favicon', async () => {
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(init.body as string))
        return response({
          ...brand,
          name: '新品牌',
          revision: 'brand-v2',
          favicon_url: '/new-icon.ico',
        })
      }
      return response(brand)
    })
  )
  mount(
    <>
      <BrandHead />
      <PlatformGeneralSettingsPage />
    </>
  )
  await page.getByRole('textbox', { name: '平台名称' }).fill('新品牌')
  await userEvent.upload(
    page.getByLabelText('横版 Logo · 浅色背景（可选）'),
    await wordmarkFile()
  )
  await expect.element(page.getByText('600 × 150 · 保存后应用')).toBeVisible()
  await page.getByRole('button', { name: '保存并应用', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({
    platform_name: '新品牌',
    revision: 'brand-v1',
    assets: { wordmark_light: { content: expect.any(String) }, favicon: null },
  })
  await expect.poll(() => document.title).toBe('品牌形象 · 新品牌')
  expect(
    document.head.querySelector('link[rel="icon"]')?.getAttribute('href')
  ).toBe('/new-icon.ico')
})

it('keeps a local draft during concurrent publication until the operator explicitly reloads', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response(brand))
  )
  const client = mount(<PlatformGeneralSettingsPage />)
  await page.getByRole('textbox', { name: '平台名称' }).fill('我的草稿')
  client.setQueryData(['platform', 'branding-settings'], {
    ...brand,
    name: '另一位管理员',
    revision: 'brand-v2',
  })
  await expect
    .element(page.getByText('品牌已由其他管理员更新', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toHaveValue('我的草稿')
  await expect
    .element(page.getByRole('button', { name: '保存并应用', exact: true }))
    .toBeDisabled()
  await page.getByRole('button', { name: '重新载入品牌' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toHaveValue('另一位管理员')
})

it('uses the selected theme artwork and never appends a duplicate name to a wordmark', async () => {
  const light = URL.createObjectURL(await wordmarkFile())
  const dark = URL.createObjectURL(await wordmarkFile())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response(brand))
  )
  mount(
    <BrandLockup
      brand={{
        ...brand,
        assets: { wordmark_light: light, wordmark_dark: dark },
      }}
      tone='dark'
    />
  )
  await expect
    .element(page.getByRole('img', { name: 'Example Platform' }))
    .toHaveAttribute('src', dark)
  await expect
    .element(page.getByText('Example Platform', { exact: true }))
    .not.toBeInTheDocument()
  URL.revokeObjectURL(light)
  URL.revokeObjectURL(dark)
})
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

it('uses default branding and keeps the edited name after a failed save', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT')
        return response({ error: { message: '保存失败，请重试' } }, 503)
      if (url.endsWith('/mail/preview'))
        return response({
          subject: 'Actvero · 组织开通邀请',
          html: '<p>邀请</p>',
        })
      if (url.endsWith('/mail')) return response(mail)
      return response({
        name: 'Actvero',
        revision: 'test-revision',
        assets: {},
        asset_ids: {},
        favicon_url: '/favicon.ico',
        apple_icon_url: '/brand/actvero-icon.png',
        identity_status: 'applied',
        smtp_configured: true,
      })
    })
  )
  mount(<PlatformGeneralSettingsPage />)
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toBeVisible()
  await page.getByRole('textbox', { name: '平台名称' }).fill('团队品牌')
  await page.getByRole('button', { name: '保存并应用', exact: true }).click()
  await expect
    .element(page.getByText('保存失败，请重试', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toHaveValue('团队品牌')
})

it('retains the unsaved name when a logo is reset', async () => {
  const saved = {
    name: 'Actvero',
    revision: 'test-revision',
    assets: { mark_light: '/logo-test.png' },
    asset_ids: { mark_light: 'test-asset' },
    favicon_url: '/favicon.ico',
    apple_icon_url: '/brand/actvero-icon.png',
    identity_status: 'applied',
    smtp_configured: true,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        saved.assets.mark_light = ''
        return response(saved)
      }
      if (url.endsWith('/mail/preview'))
        return response({ subject: '邀请', html: '<p>邀请</p>' })
      if (url.endsWith('/mail')) return response(mail)
      return response(saved)
    })
  )
  mount(<PlatformGeneralSettingsPage />)
  await page.getByRole('textbox', { name: '平台名称' }).fill('尚未保存的名称')
  await page.getByRole('button', { name: '移除方形图标', exact: true }).click()
  await expect
    .element(page.getByRole('textbox', { name: '平台名称' }))
    .toHaveValue('尚未保存的名称')
})

it('requires a new password when the SMTP destination changes', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  mount(<MailSettingsForm saved={mail} onSaved={() => {}} />)
  await expect.element(page.getByLabelText('授权码 / 密码')).toHaveValue('')
  await page
    .getByRole('textbox', { name: 'SMTP 服务器' })
    .fill('new.example.com')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect
    .element(
      page.getByText('请输入授权码；更换服务器、连接方式或账号后需重新填写。')
    )
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
})

it('saves the secret without retaining it in the query cache or input', async () => {
  const fetched: { path: string; payload: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      fetched.push({ path, payload: JSON.parse(init?.body as string) })
      return response(mail)
    })
  )
  const onSaved = vi.fn()
  const client = mount(<MailSettingsForm saved={mail} onSaved={onSaved} />)
  await page.getByLabelText('授权码 / 密码').fill('secret-test-code')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => onSaved.mock.calls.length).toBe(1)
  expect(fetched[0].payload).toMatchObject({ password: 'secret-test-code' })
  expect(
    JSON.stringify(client.getQueryData(['platform', 'mail']))
  ).not.toContain('secret-test-code')
  expect(client.getMutationCache().getAll()).toHaveLength(0)
  await expect.element(page.getByLabelText('授权码 / 密码')).toHaveValue('')
  await expect
    .element(page.getByRole('button', { name: '保存配置' }))
    .toBeDisabled()
})

it('sends a test using saved mail settings without submitting the edited configuration', async () => {
  const writes: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' || init?.method === 'PUT') {
        writes.push(`${init.method} ${url}`)
        return response({ message: '邮件已交给发件服务器' })
      }
      if (url.endsWith('/mail')) return response(mail)
      throw new Error(`Unexpected request: ${url}`)
    })
  )
  mount(<PlatformMailPage />)
  await page
    .getByRole('textbox', { name: '发件邮箱', exact: true })
    .fill('new@example.com')
  await page.getByRole('button', { name: '发送测试邮件', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog
    .getByRole('button', { name: '发送测试邮件', exact: true })
    .click()
  await expect.element(dialog.getByText('邮件已交给发件服务器')).toBeVisible()
  expect(writes).toEqual(['POST /api/v1/platform/mail/test'])
})

it('keeps the invitation lifecycle functional on its own page and removes a revoked link', async () => {
  const invitation = {
    id: 'invite-test',
    status: 'pending',
    can_copy: true,
    expires_at: '2026-10-06T12:00:00Z',
    created_at: '2026-10-03T12:00:00Z',
    organization_id: null,
    organization_name: null,
  }
  let created = false
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/mail')) return response({ ...mail, enabled: false })
      if (url.endsWith('/revoke')) {
        invitation.status = 'revoked'
        invitation.can_copy = false
        return response(invitation)
      }
      if (url.endsWith('/link'))
        return response({
          invite_url: 'https://example.com/organization-invite#test',
        })
      if (
        url.endsWith('/organization-invitations') &&
        init?.method === 'POST'
      ) {
        expect(JSON.parse(init.body as string)).toEqual({
          expires_in_hours: 72,
          recipient_email: null,
        })
        created = true
        return response({
          invitation,
          invite_url: 'https://example.com/organization-invite#test',
          mail_status: 'not_sent',
        })
      }
      if (url.endsWith('/organization-invitations'))
        return response({
          items: created ? [invitation] : [],
          total: created ? 1 : 0,
        })
      throw new Error(`Unexpected request: ${url}`)
    })
  )
  mount(<OrganizationInvitationsPage />)
  await page.getByRole('button', { name: '生成邀请', exact: true }).click()
  await page.getByRole('button', { name: '生成邀请链接', exact: true }).click()
  await expect
    .element(page.getByRole('textbox', { name: '组织邀请链接' }))
    .toBeVisible()
  await page.getByRole('button', { name: '复制', exact: true }).click()
  await expect.poll(() => copy.mock.calls.length).toBe(1)
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect.element(page.getByText('已撤销', { exact: true })).toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '组织邀请链接' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '复制', exact: true }))
    .not.toBeInTheDocument()
})

it('switches real template types without showing a previous preview after a request failure', async () => {
  let failMember = true
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method ?? 'GET').toBe('GET')
    if (url.includes('template=member_invitation')) {
      if (failMember)
        return response({ error: { message: '模板暂时不可用' } }, 503)
      return response({
        subject: 'Actvero · 组织成员邀请',
        html: '<p>成员邮件</p>',
      })
    }
    if (url.includes('template=organization_invitation'))
      return response({
        subject: 'Actvero · 组织开通邀请',
        html: '<p>开通邮件</p>',
      })
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  mount(<PlatformMailTemplatesPage />)
  await expect
    .element(page.getByText('Actvero · 组织开通邀请', { exact: true }))
    .toBeVisible()
  await page.getByRole('tab', { name: '组织成员邀请', exact: true }).click()
  await expect
    .element(page.getByText('模板暂时不可用', { exact: true }))
    .toBeVisible()
  expect(
    page.getByText('Actvero · 组织开通邀请', { exact: true }).query()
  ).toBeNull()
  failMember = false
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByText('Actvero · 组织成员邀请', { exact: true }))
    .toBeVisible()
  const frame = document.querySelector('iframe')
  expect(frame?.title).toBe('组织成员邀请邮件预览')
  expect(frame?.srcdoc).toBe('<p>成员邮件</p>')
  expect(frame?.getAttribute('sandbox')).toBe('')
  await page.getByRole('tab', { name: '组织开通邀请', exact: true }).click()
  await expect
    .element(page.getByText('Actvero · 组织开通邀请', { exact: true }))
    .toBeVisible()
  expect(document.querySelector('iframe')?.srcdoc).toBe('<p>开通邮件</p>')
  const firstTab = page.getByRole('tab', { name: '组织开通邀请', exact: true })
  firstTab.element().focus()
  await expect.element(firstTab).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  await expect
    .element(page.getByRole('tab', { name: '组织成员邀请', exact: true }))
    .toHaveAttribute('aria-selected', 'true')
  await page.viewport(390, 844)
  try {
    await expect
      .element(page.getByRole('tab', { name: '组织成员邀请' }))
      .toBeVisible()
    const tabs = page.getByRole('tablist').element()
    expect(tabs.scrollWidth).toBeLessThanOrEqual(tabs.clientWidth)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
      window.innerWidth
    )
  } finally {
    await page.viewport(1280, 900)
  }
})
