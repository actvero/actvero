import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { CategoriesDialog } from './categories-dialog'
import { CategoryPicker } from './category-picker'
import { categories } from './test-data/categories'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    user: { id: 'admin' },
    csrf: 'csrf',
  }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.classList.remove('dark')
})

async function show({ many = false, fail = false } = {}) {
  let rows = structuredClone(categories)
  if (many)
    rows = [
      ...Array.from({ length: 32 }, (_, index) => ({
        id: `custom-${index}`,
        name: `业务类别 ${index + 1}`,
        count: 0,
        revision: 1,
        system: false,
      })),
      ...rows,
    ]
  let failure = fail
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === 'GET') return Response.json(rows)
    const body = JSON.parse(String(init.body))
    if (failure) {
      failure = false
      return Response.json(
        { error: { message: '类别名称已存在' } },
        { status: 409 }
      )
    }
    const id = url.split('/')[5]
    if (init.method === 'PATCH')
      rows = rows.map((row) =>
        row.id === id
          ? { ...row, name: body.name, revision: row.revision + 1 }
          : row
      )
    else if (init.method === 'DELETE')
      rows = rows.filter((row) => row.id !== id)
    else if (url.endsWith('/move')) {
      const index = rows.findIndex((row) => row.id === id)
      const destination = index + (body.direction === 'up' ? -1 : 1)
      ;[rows[index], rows[destination]] = [rows[destination], rows[index]]
    } else
      rows.splice(rows.length - 1, 0, {
        id: 'custom-created',
        name: body.name,
        count: 0,
        revision: 1,
        system: false,
      })
    return Response.json(rows)
  })
  vi.stubGlobal('fetch', fetcher)
  const close = vi.fn()
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CategoriesDialog close={close} />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByRole('listitem', { name: '办公协同', exact: true }))
    .toBeVisible()
  return { fetcher, close }
}

it('管理员新增、改名、排序，并确认迁移删除；系统类别不能操作', async () => {
  await page.viewport(1280, 900)
  const { fetcher } = await show()
  await userEvent.fill(page.getByLabelText('新增类别'), '客户支持')
  await userEvent.click(page.getByRole('button', { name: '新增', exact: true }))
  await expect
    .element(page.getByRole('listitem', { name: '客户支持' }))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '客户支持的操作' }))
  await userEvent.click(page.getByRole('menuitem', { name: '编辑名称' }))
  await userEvent.fill(page.getByLabelText('编辑类别名称'), '客户服务')
  await userEvent.click(page.getByRole('button', { name: '保存', exact: true }))
  await expect
    .element(page.getByRole('listitem', { name: '客户服务' }))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '上移客户服务' }))
  await expect
    .poll(() =>
      page
        .getByRole('listitem')
        .elements()
        .map((el) => el.getAttribute('aria-label'))
    )
    .toEqual(['办公协同', '客户服务', '设计创意', '未分类'])
  await page.screenshot({
    path: '../../../../.local/skills-qa/categories-desktop.png',
  })
  expect(
    page
      .getByRole('listitem', { name: '未分类', exact: true })
      .element()
      .querySelector('button')
  ).toBeNull()
  await userEvent.click(page.getByRole('button', { name: '办公协同的操作' }))
  await userEvent.click(page.getByRole('menuitem', { name: '删除类别' }))
  await expect.element(page.getByRole('alertdialog')).toBeVisible()
  await userEvent.click(page.getByRole('combobox', { name: '技能迁移到' }))
  await userEvent.fill(
    page.getByRole('combobox', { name: '搜索类别…' }),
    '客户'
  )
  await userEvent.click(page.getByRole('option', { name: '客户服务' }))
  await userEvent.click(page.getByRole('button', { name: '迁移并删除' }))
  await expect.element(page.getByRole('alertdialog')).not.toBeInTheDocument()
  await expect
    .element(page.getByRole('listitem', { name: '办公协同', exact: true }))
    .not.toBeInTheDocument()
  const deletion = fetcher.mock.calls.find(
    ([, init]) => init.method === 'DELETE'
  )!
  expect(JSON.parse(String(deletion[1].body))).toEqual({
    target_id: 'custom-created',
    count: 3,
    revision: 1,
  })
  expect(deletion[1].headers).toMatchObject({ 'X-CSRF-Token': 'csrf' })
})

it('类别很多时窄屏独立滚动，新增失败保留输入，取消删除不写入', async () => {
  await page.viewport(390, 844)
  document.documentElement.classList.add('dark')
  const { fetcher } = await show({ many: true, fail: true })
  await userEvent.fill(page.getByLabelText('新增类别'), '业务重复')
  await userEvent.click(page.getByRole('button', { name: '新增', exact: true }))
  await expect.element(page.getByText('类别名称已存在')).toBeVisible()
  await expect.element(page.getByLabelText('新增类别')).toHaveValue('业务重复')
  const dialog = page.getByRole('dialog').element()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  expect(dialog.getBoundingClientRect().height).toBeLessThan(844)
  await page.screenshot({
    path: '../../../../.local/skills-qa/categories-mobile-dark.png',
  })
  await userEvent.click(page.getByRole('button', { name: '业务类别 1的操作' }))
  await userEvent.click(page.getByRole('menuitem', { name: '删除类别' }))
  await userEvent.click(page.getByRole('button', { name: '取消', exact: true }))
  expect(fetcher.mock.calls.some(([, init]) => init.method === 'DELETE')).toBe(
    false
  )
})

it('动态类别选择支持搜索和键盘，列表高度受限', async () => {
  await page.viewport(390, 844)
  const items = [
    ...Array.from({ length: 40 }, (_, i) => ({
      id: `new-${i}`,
      name: `新业务 ${i}`,
      revision: 1,
      count: 0,
      system: false,
    })),
    ...categories,
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(items))
  )
  const change = vi.fn()
  await render(
    <QueryClientProvider client={new QueryClient()}>
      <div className='p-6'>
        <CategoryPicker
          value='uncategorized'
          onValueChange={change}
          className='w-full'
          aria-label='技能类别'
        />
      </div>
    </QueryClientProvider>
  )
  await expect
    .element(page.getByRole('combobox', { name: '技能类别' }))
    .toBeEnabled()
  await userEvent.click(page.getByRole('combobox', { name: '技能类别' }))
  expect(
    page.getByRole('listbox').element().getBoundingClientRect().height
  ).toBeLessThanOrEqual(224)
  await userEvent.fill(
    page.getByRole('combobox', { name: '搜索类别…' }),
    '新业务 39'
  )
  await userEvent.keyboard('{ArrowDown}{Enter}')
  expect(change).toHaveBeenCalledWith('new-39')
  await expect.element(page.getByRole('listbox')).not.toBeInTheDocument()
})
