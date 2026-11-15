import { useState } from 'react'
import { Button as GatewayButton } from '@newapi/components/ui/button'
import {
  Tabs as GatewayTabs,
  TabsList as GatewayTabsList,
  TabsTrigger as GatewayTabsTrigger,
  TabsContent as GatewayTabsContent,
} from '@newapi/components/ui/tabs'
import { expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ListPagination } from './list-pagination'
import { Button } from './ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs'

it('分页在首页和末页阻止越界，页大小变更传出真实数值', async () => {
  const onPageSize = vi.fn()
  function Pagination() {
    const [current, setCurrent] = useState(1)
    return (
      <ListPagination
        total={45}
        page={current}
        pageCount={3}
        onPage={setCurrent}
        pageSize={20}
        onPageSize={onPageSize}
      />
    )
  }
  await render(<Pagination />)
  await expect
    .element(page.getByRole('button', { name: '上一页', exact: true }))
    .toBeDisabled()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect.element(page.getByText('第 2 / 3 页')).toBeVisible()
  await page.getByRole('button', { name: '末页', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '下一页', exact: true }))
    .toBeDisabled()
  await page.getByRole('button', { name: '首页', exact: true }).click()
  await expect.element(page.getByText('第 1 / 3 页')).toBeVisible()
  await page.getByRole('combobox', { name: '每页条数' }).click()
  await page.getByRole('option', { name: '50 条 / 页', exact: true }).click()
  expect(onPageSize).toHaveBeenCalledWith(50)
})

it('总数未知不显示零条，加载状态不能翻页', async () => {
  const onPage = vi.fn()
  await render(
    <ListPagination page={2} pageCount={3} onPage={onPage} disabled />
  )
  await expect.element(page.getByText('共 — 条')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '上一页', exact: true }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '下一页', exact: true }))
    .toBeDisabled()
  expect(onPage).not.toHaveBeenCalled()
})

it('宿主和网关共用样式后仍保留键盘表单提交和禁用语义', async () => {
  const save = vi.fn()
  await render(
    <form
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      <Button type='submit'>宿主保存</Button>
      <GatewayButton type='submit'>网关保存</GatewayButton>
      <GatewayButton type='submit' disabled>
        不可保存
      </GatewayButton>
    </form>
  )
  await page.getByRole('button', { name: '宿主保存' }).click()
  await page.getByRole('button', { name: '网关保存' }).click()
  await userEvent.keyboard('{Enter}')
  expect(save).toHaveBeenCalledTimes(3)
  await expect
    .element(page.getByRole('button', { name: '不可保存' }))
    .toBeDisabled()
})

it.each(['宿主', '网关'])(
  '%s 线形标签保持方向键切换与选中状态',
  async (kind) => {
    const Root = kind === '宿主' ? Tabs : GatewayTabs
    const List = kind === '宿主' ? TabsList : GatewayTabsList
    const Trigger = kind === '宿主' ? TabsTrigger : GatewayTabsTrigger
    const Content = kind === '宿主' ? TabsContent : GatewayTabsContent
    await render(
      <Root defaultValue='first'>
        <List variant='line' aria-label='资源配置'>
          <Trigger value='first'>资料</Trigger>
          <Trigger value='second'>定价</Trigger>
        </List>
        <Content value='first'>资料内容</Content>
        <Content value='second'>定价内容</Content>
      </Root>
    )
    await page.getByRole('tab', { name: '资料', exact: true }).click()
    await userEvent.keyboard('{ArrowRight}')
    await expect
      .element(page.getByRole('tab', { name: '定价', exact: true }))
      .toHaveFocus()
    await userEvent.keyboard('{Enter}')
    await expect
      .element(page.getByRole('tab', { name: '定价', exact: true }))
      .toHaveAttribute('aria-selected', 'true')
    await expect.element(page.getByText('定价内容')).toBeVisible()
  }
)
