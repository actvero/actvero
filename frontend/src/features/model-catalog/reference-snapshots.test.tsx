import { useForm } from 'react-hook-form'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { Button } from '@/components/ui/button'
import { Form } from '@/components/ui/form'
import { values, type ModelValues } from './model-form'
import { ReferenceSnapshots } from './reference-snapshots'

afterEach(() => {
  cleanup()
})

it('reads a persisted quote and removes only its draft snapshot after confirmation', async () => {
  const initial = values()
  initial.budget_price = { ...initial.budget_price, input: '7', output: '17' }
  initial.quote_snapshots = [
    {
      provider: 'source',
      model_id: 'model',
      fetched_at: '2026-10-06T00:00:00Z',
      source_updated_at: '2026-10-05',
      currency: 'USD',
      unit: 1000000,
      metric: 'tokens',
      source_url: null,
      raw_cost: { input: '0', output: null, tiers: [{ input: '5' }] },
      conditions: ['阶梯价格未映射'],
    },
  ]
  const inspect = vi.fn()
  function Fixture() {
    const form = useForm<ModelValues>({ defaultValues: initial })
    return (
      <Form {...form}>
        <ReferenceSnapshots />
        <Button type='button' onClick={() => inspect(form.getValues())}>
          读取草稿
        </Button>
      </Form>
    )
  }
  await render(<Fixture />)
  await page.getByRole('button', { name: '已保存参考报价（1）' }).click()
  await expect.element(page.getByText('source / model')).toBeVisible()
  await expect.element(page.getByText('阶梯价格未映射')).toBeVisible()
  await expect.element(page.getByText('0', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '移除参考报价' }).click()
  await page.getByRole('button', { name: '取消' }).click()
  await expect.element(page.getByText('source / model')).toBeVisible()
  await page.getByRole('button', { name: '移除参考报价' }).click()
  await page.getByRole('button', { name: '移除快照' }).click()
  await page.getByRole('button', { name: '读取草稿' }).click()
  const draft = inspect.mock.calls[0][0] as ModelValues
  expect(draft.quote_snapshots).toEqual([])
  expect(draft.budget_price).toEqual(initial.budget_price)
})
