import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { MemberDepartmentEditor } from './member-editor'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'test',
  }),
}))

afterEach(() => vi.unstubAllGlobals())

it('树上勾选下级不改变上级，移除主部门后保存新的主部门', async () => {
  await page.viewport(1440, 1024)
  const initial = {
    department_ids: ['east'],
    primary_department_id: 'east',
    version: 3,
  }
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/members/'))
      return Response.json(
        options.method === 'PUT'
          ? { ...JSON.parse(String(options.body)), version: 4 }
          : initial
      )
    return Response.json([
      { id: 'root', name: '总部', parent_id: null, archived: false },
      { id: 'center', name: '运营中心', parent_id: 'root', archived: false },
      { id: 'east', name: '华东运营组', parent_id: 'center', archived: false },
      { id: 'goods', name: '商品部', parent_id: 'root', archived: false },
    ])
  })
  vi.stubGlobal('fetch', fetcher)
  const close = vi.fn()
  await render(
    <QueryClientProvider client={new QueryClient()}>
      <MemberDepartmentEditor
        member={{
          id: 'member',
          name: '林晓',
          role: 'member',
          status: 'active',
          source: 'direct',
          version: 3,
          email: null,
          joined_at: '',
          is_self: false,
        }}
        close={close}
      />
    </QueryClientProvider>
  )
  const dialog = page.getByRole('dialog', { name: '设置成员部门' })
  const tree = dialog.getByRole('region', { name: '部门列表' })
  await expect
    .element(tree.getByRole('checkbox', { name: '华东运营组' }))
    .toBeChecked()
  await expect
    .element(tree.getByRole('checkbox', { name: '运营中心' }))
    .not.toBeChecked()
  await userEvent.click(tree.getByRole('button', { name: '收起 运营中心' }))
  await expect
    .element(tree.getByRole('checkbox', { name: '华东运营组' }))
    .not.toBeInTheDocument()
  const search = dialog.getByRole('textbox', { name: '搜索部门' })
  await userEvent.fill(search, '华东')
  await expect
    .element(tree.getByRole('checkbox', { name: '华东运营组' }))
    .toBeChecked()
  await userEvent.fill(search, '')
  await userEvent.click(tree.getByRole('checkbox', { name: '商品部' }))
  const selected = dialog.getByRole('region', { name: '已选部门列表' })
  await userEvent.click(
    selected.getByRole('button', { name: '移除 华东运营组' })
  )
  await expect
    .element(selected.getByText('主部门', { exact: true }))
    .toBeVisible()
  await userEvent.click(
    dialog.getByRole('button', { name: '保存', exact: true })
  )
  await expect.poll(() => close.mock.calls.length).toBe(1)
  const saved = fetcher.mock.calls.find(
    ([, request]) => request.method === 'PUT'
  )
  expect(JSON.parse(String(saved?.[1].body))).toEqual({
    department_ids: ['goods'],
    primary_department_id: 'goods',
    version: 3,
  })
})
