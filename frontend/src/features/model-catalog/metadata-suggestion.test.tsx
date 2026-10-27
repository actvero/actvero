import { useForm, useWatch } from 'react-hook-form'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { Form } from '@/components/ui/form'
import { MetadataSuggestion } from './metadata-suggestion'
import { values } from './model-form'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({ organization: { tenant_id: 'metadata' } }),
}))
const reference = {
  provider: 'openai',
  model_id: 'example-model',
  name: 'Public name',
  developer_name: 'OpenAI',
  context_window: 9000,
  max_output: 600,
  capabilities: { tools: 'supported', reasoning: 'unknown' },
  reasoning_options: [],
  price: { currency: 'USD', input: '4', output: '8' },
}
let client: QueryClient
function Harness() {
  const draft = values()
  draft.name = 'My name'
  draft.slug = 'my-model'
  draft.context_window = '12345'
  draft.reference = { provider: 'openai', model_id: 'example-model' }
  const form = useForm({ defaultValues: draft })
  useWatch({ control: form.control })
  return (
    <Form {...form}>
      <MetadataSuggestion />
      <output aria-label='配置结果'>{JSON.stringify(form.getValues())}</output>
    </Form>
  )
}
async function show(items: unknown[], failed = false) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        failed ? { error: { message: 'offline' } } : { items, stale: false },
        { status: failed ? 502 : 200 }
      )
    )
  )
  await render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>
  )
}
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  vi.unstubAllGlobals()
})
it('fills only missing metadata from an exact provider and model match, preserving names and prices', async () => {
  await show([reference])
  await page.getByRole('button', { name: '补全空白参数' }).click()
  await expect
    .element(page.getByRole('button', { name: '已补全空白参数' }))
    .toBeDisabled()
  const result = JSON.parse(
    page.getByLabelText('配置结果').element().textContent!
  )
  expect(result).toMatchObject({
    name: 'My name',
    slug: 'my-model',
    context_window: '12345',
    max_output: '600',
    capabilities: { tools: 'supported' },
    budget_price: { enabled: false, input: '', output: '' },
  })
})
it('does not offer another provider with the same model ID as an exact match', async () => {
  await show([{ ...reference, provider: 'another-provider' }])
  await expect
    .element(
      page.getByText(
        '未找到相同供应商和模型 ID 的资料。可手动填写，或通过“从公开资料补全”查找并核对其他来源。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '补全空白参数' }))
    .not.toBeInTheDocument()
})
it('leaves the form usable when public metadata cannot be read', async () => {
  await show([], true)
  await expect
    .element(page.getByText('公开资料暂不可用，已填写内容不受影响。'))
    .toBeVisible()
  const result = JSON.parse(
    page.getByLabelText('配置结果').element().textContent!
  )
  expect(result.context_window).toBe('12345')
  expect(result.max_output).toBe('')
})
