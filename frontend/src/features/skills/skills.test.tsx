import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { Markdown } from '@/components/markdown'
import { FileBrowser } from './file-tree'
import { MetadataDialog } from './metadata-dialog'
import type { Skill } from './shared'
import { categories } from './test-data/categories'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    user: { id: 'test-admin' },
    csrf: 'test-csrf',
  }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
const skill: Skill = {
  id: 'test-skill',
  name: 'test-skill',
  category: 'office',
  category_name: '办公协同',
  display_name: '验收技能',
  description: '技能简介',
  audience: 'organization',
  member_ids: [],
  revision: 3,
  default_version_id: null,
  versions: [],
  downloads: 0,
  created_at: '2026-09-24T00:00:00Z',
}
async function show(component: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {component}
    </QueryClientProvider>
  )
}
it('Markdown 不执行 HTML，不加载远程图片，不允许脚本链接', async () => {
  const screen = await show(
    <Markdown>
      {
        '# 技能说明\n<script>alert(1)</script>\n[危险](javascript:alert%281%29)\n![远程图片](https://example.com/tracker.png)\n[官方文档](https://example.com)'
      }
    </Markdown>
  )
  await expect
    .element(screen.getByRole('heading', { name: '技能说明' }))
    .toBeVisible()
  expect(document.querySelector('script[src="https://example.com"]')).toBeNull()
  expect(document.querySelector('img')).toBeNull()
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull()
  await expect
    .element(screen.getByRole('link', { name: '官方文档' }))
    .toHaveAttribute('rel', 'noopener noreferrer')
})
it('文件树支持键盘展开与只读文件选择', async () => {
  const select = vi.fn()
  const files = [
    { path: 'SKILL.md', size: 321, previewable: true, sha256: 'test-a' },
    {
      path: 'references/example.md',
      sha256: 'test-b',
      size: 128,
      previewable: true,
    },
  ]
  await show(<FileBrowser files={files} onSelect={select} />)
  await userEvent.click(page.getByRole('button', { name: 'references' }))
  await userEvent.click(page.getByRole('button', { name: 'example.md 128 B' }))
  expect(select).toHaveBeenCalledWith(files[1])
})
it('指定成员不能空提交；范围保存为技能级且保留并发版本', async () => {
  await page.viewport(1100, 900)
  const fetcher = vi.fn(async (url: string) =>
    Response.json(
      url.endsWith('/categories')
        ? categories
        : url.includes('/icon-catalog')
          ? []
          : url.includes('/members')
            ? { items: [], total: 0, page: 1 }
            : skill
    )
  )
  vi.stubGlobal('fetch', fetcher)
  await show(<MetadataDialog skill={skill} close={() => {}} />)
  await userEvent.click(page.getByRole('combobox', { name: '使用范围' }))
  await userEvent.click(page.getByRole('option', { name: '指定成员' }))
  await userEvent.click(page.getByRole('button', { name: '保存设置' }))
  await expect.element(page.getByText('请至少选择一名成员')).toBeVisible()
  expect(
    fetcher.mock.calls.some(([url]) => url === '/api/v1/skills/test-skill')
  ).toBe(false)
  await userEvent.click(page.getByRole('combobox', { name: '使用范围' }))
  await userEvent.click(page.getByRole('option', { name: '仅管理员' }))
  await userEvent.click(
    page.getByRole('combobox', { name: '类别', exact: true })
  )
  await userEvent.click(page.getByRole('option', { name: '设计创意' }))
  await userEvent.click(page.getByRole('button', { name: '保存设置' }))
  await expect
    .poll(() =>
      fetcher.mock.calls.some(([url]) => url === '/api/v1/skills/test-skill')
    )
    .toBe(true)
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([url]) => url === '/api/v1/skills/test-skill')!
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    audience: 'administrators',
    category: 'design',
    member_ids: [],
    revision: 3,
  })
  expect(call[1]?.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
})
it('技能设置在 390px 窄屏内可提交，字段不横向溢出', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(url.endsWith('/categories') ? categories : [])
    )
  )
  await page.viewport(390, 844)
  await show(<MetadataDialog skill={skill} close={() => {}} />)
  await page.screenshot({
    path: '../../../../.local/skills-qa/category-mobile.png',
  })
  const dialog = page.getByRole('dialog').element()
  expect(dialog.getBoundingClientRect().width).toBeLessThanOrEqual(390)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await expect
    .element(page.getByRole('button', { name: '保存设置' }))
    .toBeVisible()
})

it('版本对比按文件摘要识别变化，并通过受权文件接口读取原文', async () => {
  const { CompareDialog } = await import('./compare-dialog')
  const common = {
    status: 'published' as const,
    package_icon: '',
    icon_warning: '',
    release_notes: '',
    uploader_name: '测试管理员',
    size: 300,
    created_at: '2026-09-24T00:00:00Z',
    published_at: '2026-09-24T00:00:00Z',
  }
  const before = {
    ...common,
    id: 'old',
    version: '1.0.0',
    sha256: 'old-zip',
    files: [
      { path: 'SKILL.md', size: 100, previewable: true, sha256: 'old-content' },
      { path: 'LICENSE', size: 200, previewable: true, sha256: 'same' },
    ],
  }
  const after = {
    ...common,
    id: 'new',
    version: '1.1.0',
    sha256: 'new-zip',
    files: [
      { path: 'SKILL.md', size: 100, previewable: true, sha256: 'new-content' },
      { path: 'LICENSE', size: 200, previewable: true, sha256: 'same' },
    ],
  }
  const fetcher = vi.fn(async (url: string) =>
    Response.json({
      path: 'SKILL.md',
      content: url.includes('/old/') ? '旧版正文' : '新版正文',
    })
  )
  vi.stubGlobal('fetch', fetcher)
  await page.viewport(1100, 900)
  await show(
    <CompareDialog
      skill={{ ...skill, versions: [after, before] }}
      target={after}
      close={() => {}}
    />
  )
  await expect.element(page.getByText('旧版正文')).toBeVisible()
  await expect.element(page.getByText('新版正文')).toBeVisible()
  expect(
    fetcher.mock.calls.every(
      ([url]) =>
        url.startsWith('/api/v1/skills/test-skill/versions/') &&
        url.includes('/file?path=SKILL.md')
    )
  ).toBe(true)
  await expect
    .element(page.getByRole('button', { name: '修改 SKILL.md' }))
    .toBeVisible()
  expect(page.getByText('LICENSE').elements()).toHaveLength(0)
})
