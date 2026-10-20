import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { endpointReasonLabel } from '@/features/model-catalog/endpoint-status'
import { routeStates } from '@/features/model-catalog/model-form'
import { DetailHealth } from './detail-health'
import type { Detail } from './shared'

const base = {
  id: 'channel-id',
  name: '停用的渠道',
  description: '',
  icon: '',
  provider: 'openai-compatible',
  version: 5,
  base_url: 'https://example.test/v1',
  connection: {
    address_mode: 'legacy_api_base',
    legacy_base_url: 'https://example.test/v1',
    resolver_version: 1,
  },
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  manual_enabled: false,
  automatic_protection: { enabled: false },
  models: [
    {
      id: 'upstream-a',
      source: 'manual',
      registered_at: '2026-10-04T00:00:00Z',
    },
  ],
  model_count: 1,
  checks: [],
  last_check: null,
  created_at: '2026-10-04T00:00:00Z',
  health_summary: {
    state: 'unavailable',
    health_counts: { credential_error: 1, model_error: 1, binding_error: 2 },
    as_of: '2026-10-04T01:00:00Z',
  },
} as Detail

function reference(state: string, name: string, reason?: string) {
  return {
    binding_id: `binding-${name}`,
    model_id: `model-${name}`,
    model_name: name,
    model_version: 4,
    operation: 'chat',
    upstream_model_id: `upstream-${name}`,
    binding_enabled: true,
    model_archived: false,
    model_enabled: true,
    operation_enabled: true,
    source_registered: true,
    health_state: state,
    health_block_reason: reason ?? null,
  }
}

beforeEach(async () => page.viewport(1280, 900))
afterEach(async () => {
  await cleanup()
  vi.restoreAllMocks()
})

it('distinguishes credential, model and binding error scopes while manual state stays separate', async () => {
  await page.viewport(390, 1600)
  expect(endpointReasonLabel('model_error')).toBe('上游模型不可用')
  expect(endpointReasonLabel('binding_error')).toBe('绑定拒绝待判')
  expect(routeStates.credential_error).toBe('渠道凭据阻断')
  expect(routeStates.model_error).toBe('上游模型不可用')
  expect(routeStates.binding_error).toBe('绑定拒绝待判')
  const showTest = vi.fn()
  await render(
    <DetailHealth
      channel={
        {
          ...base,
          binding_references: [
            reference('credential_error', '凭据模型'),
            reference('model_error', '上游模型', 'model_unavailable'),
            reference('binding_error', '待判绑定', 'unclassified_rejection'),
            reference('binding_error', '旧绑定'),
          ],
        } as Detail
      }
      testOperations={['chat']}
      showTest={showTest}
    />
  )
  await expect.element(page.getByText('已停用', { exact: true })).toBeVisible()
  await expect
    .element(page.getByText('阻断或等待 4 条', { exact: false }))
    .toBeVisible()
  await expect
    .element(
      page.getByText('可靠的渠道凭据拒绝；同一渠道凭据范围受阻，请核对凭据。')
    )
    .toBeVisible()
  await expect
    .element(
      page.getByText(
        '上游确认此模型不可用；相关模型目标受阻，其他模型不因此关闭。'
      )
    )
    .toBeVisible()
  await expect
    .element(
      page.getByText(
        '上游 403/404 的原因尚未判明；仅此绑定暂停，不能推断整个渠道凭据失效。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByText('拒绝范围尚未判明；仅此绑定暂停。'))
    .toBeVisible()
  await expect
    .element(
      page.getByText(
        '已关闭一般故障冷却。认证错误和上游限流仍由执行服务处理；平台不再根据历史测试结果阻止调用。'
      )
    )
    .toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-g4-health-three-scopes-390.png',
  })
  await page.getByRole('button', { name: '诊断此绑定' }).first().click()
  expect(showTest).toHaveBeenCalledWith('upstream-凭据模型', 'chat')
})

it('keeps historical cooldown visible without blocking a new diagnostic', async () => {
  await page.viewport(390, 844)
  const showTest = vi.fn()
  await render(
    <DetailHealth
      channel={
        {
          ...base,
          binding_references: [
            {
              ...reference('cooldown', '等待模型'),
              cooldown_until: '2100-01-03T12:00:00Z',
            },
          ],
        } as Detail
      }
      testOperations={['chat']}
      showTest={showTest}
    />
  )
  await expect.element(page.getByText(/冷却截止/)).toBeVisible()
  await expect
    .element(page.getByText(/历史冷却状态仅供排障，实际调用由执行服务调度/))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '诊断此绑定' }))
    .toBeEnabled()
  await expect
    .element(page.getByRole('button', { name: '验证此绑定' }))
    .toBeEnabled()
  await page.screenshot({
    path: '__screenshots__/actvero-g4-health-cooldown-390.png',
  })
  await page.getByRole('button', { name: '诊断此绑定' }).click()
  expect(showTest).toHaveBeenCalledWith('upstream-等待模型', 'chat')
})

it('hides new diagnostic actions for an archived channel at 390px', async () => {
  await page.viewport(390, 844)
  await render(
    <DetailHealth
      channel={
        {
          ...base,
          archived: true,
          binding_references: [
            reference('model_error', '归档模型', 'model_unavailable'),
          ],
        } as Detail
      }
      testOperations={['chat']}
      showTest={vi.fn()}
    />
  )
  await expect.element(page.getByText('不适用（已归档）')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '诊断此绑定' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '验证此绑定' }))
    .not.toBeInTheDocument()
  await page.screenshot({ path: '__screenshots__/actvero-g4-health-390.png' })
})
