import { useForm } from 'react-hook-form'
import '@/styles/index.css'
import { afterEach, expect, it } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { Form } from '@/components/ui/form'
import type { ChannelValues } from './channel-form'
import { ChannelModelFields } from './channel-model-fields'

function Picker({
  candidates,
  discovered = true,
}: {
  candidates: string[]
  discovered?: boolean
}) {
  const form = useForm<ChannelValues>({
    defaultValues: { models: [], manual_models: '' },
  })
  return (
    <Form {...form}>
      <ChannelModelFields
        candidates={candidates}
        discovered={discovered}
        partial={false}
        pending={false}
        discovering={false}
        discover={() => undefined}
        modelDiscovery
      />
    </Form>
  )
}
afterEach(cleanup)

it('shows fetched models without a search and preserves the filter while selecting multiple models', async () => {
  await render(<Picker candidates={['chat-one', 'chat-two', 'embed-one']} />)
  await expect
    .element(page.getByRole('button', { name: 'chat-one', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('上游返回 3 个模型 · 已选 0 个'))
    .toBeVisible()
  await page.getByRole('textbox', { name: '搜索或输入模型 ID' }).fill('chat')
  await page.getByRole('button', { name: 'chat-one', exact: true }).click()
  await expect
    .element(page.getByRole('textbox', { name: '搜索或输入模型 ID' }))
    .toHaveValue('chat')
  await page.getByRole('button', { name: '全选匹配结果' }).click()
  await expect
    .element(page.getByText('上游返回 3 个模型 · 已选 2 个'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '移除 embed-one', exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: 'chat-one', exact: true }).click()
  await expect
    .element(page.getByText('上游返回 3 个模型 · 已选 1 个'))
    .toBeVisible()
})

it('explains an empty upstream response and still accepts an explicit model ID', async () => {
  await render(<Picker candidates={[]} />)
  await expect
    .element(page.getByText('上游返回了空目录，可继续输入实际模型 ID。'))
    .toBeVisible()
  await page
    .getByRole('textbox', { name: '搜索或输入模型 ID' })
    .fill('private-model')
  await page
    .getByRole('button', { name: '添加自定义模型 ID：private-model' })
    .click()
  await expect
    .element(page.getByRole('button', { name: '移除 private-model' }))
    .toBeVisible()
})
