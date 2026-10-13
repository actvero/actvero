/** Isolated fixtures exercise the real settings form, picker and cropper. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import catalog from '../../../../backend/app/modules/skills/assets/icons.json'
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
  document.documentElement.classList.remove('dark')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
const skill: Skill = {
  id: 'icon-fixture',
  name: 'document-summary',
  category: 'office',
  category_name: '办公协同',
  display_name: '文档整理',
  description: '整理文档并生成摘要',
  audience: 'organization',
  member_ids: [],
  revision: 3,
  default_version_id: null,
  versions: [],
  downloads: 0,
  created_at: '2026-09-24T00:00:00Z',
}

async function show(seed = skill) {
  const requests = vi.fn(async (url: string) =>
    Response.json(
      url.endsWith('/categories')
        ? categories
        : url.endsWith('/icon-catalog')
          ? catalog.items
          : seed
    )
  )
  vi.stubGlobal('fetch', requests)
  const close = vi.fn()
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MetadataDialog skill={seed} close={close} />
    </QueryClientProvider>
  )
  return { requests, close }
}
function writes(requests: ReturnType<typeof vi.fn>) {
  return requests.mock.calls.filter(([, init]) => init?.method === 'PUT')
}

it.each([
  [1100, 900],
  [390, 844],
  [1024, 500],
  [360, 640],
])(
  '搜索聚焦外圈完整，图标滚动不挤压搜索与操作：%i×%i',
  async (width, height) => {
    await page.viewport(width, height)
    await show()
    await userEvent.click(page.getByRole('button', { name: '编辑技能图标' }))
    const dialog = page.getByRole('dialog', { name: '选择技能图标' })
    const input = page.getByRole('textbox', { name: '搜索图标' })
    await userEvent.click(input)
    await expect.element(input).toHaveFocus()
    const node = input.element() as HTMLInputElement
    const rect = node.getBoundingClientRect()
    expect(rect.height).toBeGreaterThanOrEqual(35)
    expect(getComputedStyle(node).boxShadow).not.toBe('none')
    // The 3px focus ring must fit inside every clipping ancestor on both axes.
    for (
      let parent = node.parentElement;
      parent;
      parent = parent.parentElement
    ) {
      const style = getComputedStyle(parent)
      const bounds = parent.getBoundingClientRect()
      if (['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowX)) {
        expect(rect.left - 3).toBeGreaterThanOrEqual(
          bounds.left + parent.clientLeft - 1
        )
        expect(rect.right + 3).toBeLessThanOrEqual(
          bounds.left + parent.clientLeft + parent.clientWidth + 1
        )
      }
      if (['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowY)) {
        expect(rect.top - 3).toBeGreaterThanOrEqual(
          bounds.top + parent.clientTop - 1
        )
        expect(rect.bottom + 3).toBeLessThanOrEqual(
          bounds.top + parent.clientTop + parent.clientHeight + 1
        )
      }
    }
    const list = page.getByLabelText('可选图标').element()
    expect(list.scrollHeight).toBeGreaterThan(list.clientHeight)
    list.scrollTop = 500
    expect(node.getBoundingClientRect().top).toBeCloseTo(rect.top, 0)
    expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
      dialog.element().clientWidth + 1
    )
    await dialog.screenshot({
      path: `../../../../.local/skills-qa/icons-focus-${width}x${height}.png`,
    })
    await userEvent.click(page.getByRole('button', { name: '取消选择' }))
    await expect
      .element(page.getByRole('button', { name: '编辑技能图标' }))
      .toHaveFocus()
  }
)

it('搜索选择图标可取消；只有保存技能设置才持久化，并带 revision 与 CSRF', async () => {
  await page.viewport(1100, 900)
  const { requests, close } = await show()
  await userEvent.click(page.getByRole('button', { name: '编辑技能图标' }))
  await expect
    .element(page.getByRole('button', { name: '文档', exact: true }))
    .toBeVisible()
  await page
    .getByRole('dialog', { name: '选择技能图标' })
    .screenshot({ path: '../../../../.local/skills-qa/icons-library.png' })
  await userEvent.fill(
    page.getByRole('textbox', { name: '搜索图标' }),
    '不存在'
  )
  await expect
    .element(page.getByText('没有匹配的图标，试试其他关键词。'))
    .toBeVisible()
  await userEvent.fill(page.getByRole('textbox', { name: '搜索图标' }), '文档')
  await userEvent.click(page.getByRole('button', { name: '文档', exact: true }))
  await expect
    .element(page.getByRole('button', { name: '文档', exact: true }))
    .toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(page.getByRole('button', { name: '取消选择' }))
  await expect
    .element(page.getByRole('button', { name: '编辑技能图标' }))
    .toHaveFocus()
  expect(writes(requests)).toHaveLength(0)
  await userEvent.click(page.getByRole('button', { name: '编辑技能图标' }))
  await expect.element(page.getByText('已选：跟随技能包')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '文档', exact: true }))
  await userEvent.click(page.getByRole('button', { name: '使用此图标' }))
  expect(writes(requests)).toHaveLength(0)
  await page
    .getByRole('dialog', { name: '技能设置', exact: true })
    .screenshot({ path: '../../../../.local/skills-qa/icons-settings.png' })
  await userEvent.click(page.getByRole('button', { name: '保存设置' }))
  await expect.poll(() => writes(requests).length).toBe(1)
  const [, init] = writes(requests)[0]
  expect(JSON.parse(init.body)).toMatchObject({
    revision: 3,
    icon_selection: { source: 'library', key: 'lucide:file-text' },
  })
  expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
  await expect.poll(() => close.mock.calls.length).toBe(1)
})

it('手动图标可以恢复自动，取消整个设置不写入；窄屏暗色无溢出', async () => {
  await page.viewport(390, 844)
  document.documentElement.classList.add('dark')
  const { requests } = await show({
    ...skill,
    icon_selection: { source: 'library', key: 'lucide:palette', image: '' },
  })
  await userEvent.click(page.getByRole('button', { name: '编辑技能图标' }))
  const dialog = page.getByRole('dialog', { name: '选择技能图标' })
  expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
    dialog.element().clientWidth + 1
  )
  await dialog.screenshot({
    path: '../../../../.local/skills-qa/icons-mobile-dark.png',
  })
  await userEvent.click(page.getByRole('tab', { name: '跟随技能包' }))
  await expect
    .element(page.getByText('暂无包内图标，显示名称首字母'))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '恢复自动' }))
  await userEvent.click(page.getByRole('button', { name: '使用此图标' }))
  await userEvent.click(page.getByRole('button', { name: '取消', exact: true }))
  expect(writes(requests)).toHaveLength(0)
})

it('上传图片在共享裁剪弹窗中裁剪，保存后提交规范的图像数据', async () => {
  await page.viewport(1100, 900)
  const { requests } = await show()
  await userEvent.click(page.getByRole('button', { name: '编辑技能图标' }))
  await userEvent.click(page.getByRole('tab', { name: '上传图片' }))
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 64
  const context = canvas.getContext('2d')!
  context.fillRect(0, 0, 64, 64)
  const blob = await new Promise<Blob>((resolve) =>
    canvas.toBlob((value) => resolve(value!), 'image/png')
  )
  await userEvent.upload(
    page.getByLabelText('选择上传图标'),
    new File([blob], 'icon.png', { type: 'image/png' })
  )
  await expect
    .element(page.getByRole('button', { name: '应用裁剪' }))
    .toBeEnabled()
  await userEvent.click(page.getByRole('button', { name: '应用裁剪' }))
  await expect.element(page.getByText('已选：上传图片')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '使用此图标' }))
  await userEvent.click(page.getByRole('button', { name: '保存设置' }))
  await expect.poll(() => writes(requests).length).toBe(1)
  const choice = JSON.parse(writes(requests)[0][1].body).icon_selection
  expect(choice.source).toBe('upload')
  expect(choice.image).toMatch(/^data:image\/webp;base64,/)
})
