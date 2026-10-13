import { useState } from 'react'
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { TokenEstimate } from './capability-controls'
import { shortTokens } from './capability-data'
import { CapabilityPanel, RunPanel } from './capability-panel'
import { ConnectionDialog } from './connection-dialog'
import { ImportDialog } from './import-dialog'
import { Presentation } from './presentation'
import { ServiceCard } from './service-card'
import { ServiceEditor } from './service-editor'
import { useMcp, type Service, type Capability } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'organization' },
    user: { id: 'test-user' },
    csrf: 'test-csrf',
  }),
}))
const service: Service = {
  id: 'service',
  name: '协议测试',
  description: '',
  display_name: '',
  icon: '',
  examples: [],
  audience: 'organization',
  transport: 'http',
  url: 'https://example.com/mcp',
  version: 1,
  configured: true,
  checked_at: '2026-09-23T12:00:00Z',
  error: null,
  protocol: '2025-11-25',
  counts: { tools: 1, prompts: 1 },
  enabled: false,
  auth_mode: 'personal',
  credential_fields: [
    { key: 'token', label: 'API Key', header: 'Authorization', bearer: true },
  ],
}
const tool: Capability = {
  kind: 'tools',
  key: 'sum',
  name: 'sum',
  description: '求和',
  original_description: '求和',
  enabled: false,
  definition: {
    inputSchema: {
      type: 'object',
      properties: { a: { type: 'number' } },
      required: ['a'],
    },
  },
}
async function screen(component: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    client,
    page: await render(
      <QueryClientProvider client={client}>{component}</QueryClientProvider>
    ),
  }
}
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
function Panel() {
  const [tab, setTab] = useState('tools')
  return <CapabilityPanel service={service} tab={tab} onTab={setTab} />
}
describe('MCP 工作台', () => {
  it('切换能力标签和展开详情不会调用上游工具', async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        items: [
          tool,
          { ...tool, kind: 'prompts', key: 'hello', name: 'hello' },
        ],
        protocol: '2025-11-25',
        negotiated: {},
        checked_at: '2026-09-23T12:00:00Z',
        error: null,
      })
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<Panel />)
    await userEvent.click(page.getByRole('button', { name: '展开 sum' }))
    await expect
      .element(page.getByText('inputSchema', { exact: false }))
      .toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '更多能力操作 sum' }))
      .toBeVisible()
    await userEvent.click(page.getByRole('tab', { name: '提示词 1' }))
    await expect.element(page.getByText('hello', { exact: true })).toBeVisible()
    await userEvent.click(page.getByRole('button', { name: '展开 hello' }))
    await expect
      .element(page.getByRole('button', { name: '编辑说明', exact: true }))
      .not.toBeInTheDocument()
    await expect
      .element(page.getByRole('button', { name: '恢复原说明', exact: true }))
      .not.toBeInTheDocument()
    await expect
      .element(page.getByRole('button', { name: '连接详情', exact: true }))
      .not.toBeInTheDocument()
    expect(fetcher.mock.calls.length).toBe(1)
  })
  it('更多菜单打开设置和删除确认，取消后焦点回到菜单且不修改服务', async () => {
    const fetcher = vi.fn(async () => Response.json({ items: [tool] }))
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<ServiceCard service={service} />)
    const trigger = page.getByRole('button', { name: '更多服务操作 协议测试' })
    await userEvent.click(trigger)
    await userEvent.click(
      page.getByRole('menuitem', { name: '编辑', exact: true })
    )
    await expect
      .element(page.getByRole('dialog', { name: '编辑服务：协议测试' }))
      .toBeVisible()
    await expect
      .element(page.getByLabelText('服务名称'))
      .toHaveValue('协议测试')
    await expect
      .element(page.getByLabelText('服务地址'))
      .toHaveValue('https://example.com/mcp')
    await expect
      .element(page.getByRole('button', { name: '编辑MCP 服务头像' }))
      .toBeVisible()
    await userEvent.click(
      page.getByRole('button', { name: '取消', exact: true })
    )
    await expect.element(trigger).toHaveFocus()
    await userEvent.click(trigger)
    await userEvent.click(page.getByRole('menuitem', { name: '删除服务' }))
    await expect.element(page.getByRole('alertdialog')).toBeVisible()
    await userEvent.click(
      page.getByRole('button', { name: '取消', exact: true })
    )
    await expect.element(trigger).toHaveFocus()
    expect(fetcher.mock.calls.length).toBe(1)
  })
  it('只有明确运行才提交，带 CSRF，结果不进入查询缓存', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({
        result: { content: [{ type: 'text', text: 'computed' }] },
        duration_ms: 10,
      })
    )
    vi.stubGlobal('fetch', fetcher)
    const { page, client } = await screen(
      <RunPanel service={service} item={tool} close={() => {}} />
    )
    expect(fetcher).not.toHaveBeenCalled()
    await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
    await userEvent.fill(page.getByLabelText('参数（JSON）'), '{"a":7}')
    await userEvent.click(
      page.getByRole('button', { name: '运行', exact: true })
    )
    await expect
      .element(page.getByText('computed', { exact: false }))
      .toBeVisible()
    const [, options] = fetcher.mock.calls[0]
    expect(options.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
    expect(JSON.parse(String(options.body)).arguments).toEqual({ a: 7 })
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
  it('非法 JSON 保留表单并不发起调用', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(
      <RunPanel service={service} item={tool} close={() => {}} />
    )
    await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
    await userEvent.fill(page.getByLabelText('参数（JSON）'), '[]')
    await userEvent.click(
      page.getByRole('button', { name: '运行', exact: true })
    )
    await expect.element(page.getByText('参数必须为 JSON 对象')).toBeVisible()
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('凭据不回显、不进入 Query 或 Mutation 缓存', async () => {
    const fetcher = vi.fn(async () => Response.json({ message: 'saved' }))
    vi.stubGlobal('fetch', fetcher)
    const close = vi.fn()
    const { page, client } = await screen(
      <ConnectionDialog service={service} close={close} />
    )
    await expect
      .element(page.getByLabelText('API Key', { exact: true }))
      .toHaveValue('')
    await userEvent.fill(
      page.getByLabelText('API Key', { exact: true }),
      'test-secret-value'
    )
    await userEvent.click(page.getByRole('button', { name: '保存凭据' }))
    await expect.poll(() => close.mock.calls.length).toBe(1)
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data)
      )
    ).not.toContain('test-secret-value')
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
})

describe('MCP 配置优化', () => {
  it('连接设置使用分段选择，自动生成凭据标识，保留指定成员和展示配置', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json(
        _url.includes('/members?') ? { items: [], total: 0, page: 1 } : {}
      )
    )
    vi.stubGlobal('fetch', fetcher)
    const selected = {
      ...service,
      audience: 'selected' as const,
      member_ids: ['member-a'],
      display_name: '业务文档',
      description: '单一简介',
      examples: ['查找文档'],
    }
    const { page, client } = await screen(
      <ServiceEditor service={selected} close={() => {}} />
    )
    await expect
      .element(page.getByRole('radio', { name: 'Streamable HTTP' }))
      .toBeChecked()
    await expect
      .element(page.getByText('字段标识', { exact: true }))
      .not.toBeInTheDocument()
    await expect
      .element(page.getByText('启用后谁可以看到和使用'))
      .not.toBeInTheDocument()
    await userEvent.fill(
      page.getByLabelText('简介', { exact: true }),
      '搜索和阅读文档'
    )
    await userEvent.fill(page.getByLabelText('输入框名称'), '个人访问令牌')
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect
      .poll(
        () =>
          fetcher.mock.calls.filter(([, options]) => options.method === 'PUT')
            .length
      )
      .toBe(1)
    const body = JSON.parse(
      String(
        fetcher.mock.calls.find(([, options]) => options.method === 'PUT')![1]
          .body
      )
    )
    expect(body).toMatchObject({
      audience: 'selected',
      member_ids: ['member-a'],
      display_name: '业务文档',
      description: '搜索和阅读文档',
      examples: ['查找文档'],
    })
    expect(body.credential_fields[0]).toMatchObject({
      key: 'token',
      label: '个人访问令牌',
      header: 'Authorization',
      bearer: true,
    })
    expect(body.credential_values).toBeUndefined()
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
  it('旧内置服务也用添加表单编辑，可改连接方式、地址和认证后保存', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({})
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(
      <ServiceEditor
        service={{
          ...service,
          transport: 'builtin',
          url: '',
          auth_mode: 'none',
          credential_fields: [],
        }}
        close={() => {}}
      />
    )
    await expect
      .element(page.getByRole('radio', { name: '内置内容', exact: true }))
      .not.toBeInTheDocument()
    await expect
      .element(page.getByRole('radio', { name: 'Streamable HTTP' }))
      .toBeChecked()
    await expect
      .element(page.getByLabelText('服务名称'))
      .toHaveValue(service.name)
    await expect.element(page.getByLabelText('服务地址')).toHaveValue('')
    await expect.element(page.getByLabelText('服务地址')).toBeEnabled()
    await expect
      .element(page.getByRole('combobox', { name: '认证方式' }))
      .toBeEnabled()
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect
      .element(page.getByText('请输入完整 HTTP(S) 服务地址'))
      .toBeVisible()
    expect(fetcher).not.toHaveBeenCalled()
    await userEvent.click(page.getByRole('radio', { name: 'SSE（旧版）' }))
    await userEvent.fill(page.getByLabelText('服务名称'), '验收服务新名称')
    await userEvent.fill(
      page.getByLabelText('简介', { exact: true }),
      '连接企业文档'
    )
    await userEvent.fill(
      page.getByLabelText('服务地址'),
      'https://example.com/sse'
    )
    await userEvent.click(page.getByRole('combobox', { name: '认证方式' }))
    await userEvent.click(page.getByRole('option', { name: '个人凭据' }))
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect.poll(() => fetcher.mock.calls.length).toBe(1)
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toMatchObject({
      name: '验收服务新名称',
      description: '连接企业文档',
      transport: 'sse',
      url: 'https://example.com/sse',
      auth_mode: 'personal',
      credential_fields: [
        {
          key: 'token',
          label: 'API Key',
          header: 'Authorization',
          bearer: true,
        },
      ],
    })
  })
  it('已配置组织凭据留空可保存范围，修改地址仍要求重新填写', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({})
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(
      <ServiceEditor
        service={{ ...service, auth_mode: 'organization', configured: true }}
        close={() => {}}
      />
    )
    await userEvent.click(page.getByRole('combobox', { name: '可使用成员' }))
    await userEvent.click(page.getByRole('option', { name: '仅管理员' }))
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect.poll(() => fetcher.mock.calls.length).toBe(1)
    const body = JSON.parse(String(fetcher.mock.calls[0][1].body))
    expect(body).toMatchObject({ audience: 'selected', member_ids: [] })
    expect(body.credential_values).toBeUndefined()
    await userEvent.fill(page.getByLabelText('服务地址'), 'https://other.example/mcp')
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect.element(page.getByText('请完整填写组织凭据')).toBeVisible()
    expect(fetcher.mock.calls).toHaveLength(1)
  })
  it('组织凭据和连接配置一次提交，密钥不进入查询缓存', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({})
    )
    vi.stubGlobal('fetch', fetcher)
    const { page, client } = await screen(
      <ServiceEditor
        service={{ ...service, auth_mode: 'organization', configured: false }}
        close={() => {}}
      />
    )
    await userEvent.fill(
      page.getByLabelText('API Key', { exact: true }),
      'organization-test-secret'
    )
    await userEvent.click(page.getByRole('button', { name: '保存配置' }))
    await expect.poll(() => fetcher.mock.calls.length).toBe(1)
    expect(
      JSON.parse(String(fetcher.mock.calls[0][1].body)).credential_values
    ).toEqual({ token: 'organization-test-secret' })
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data)
      )
    ).not.toContain('organization-test-secret')
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
  it('导入先预览且不显示明文密钥，确认前不写入', async () => {
    const fetcher = vi.fn(async (url: string, _options: RequestInit) =>
      Response.json(
        url.endsWith('/preview')
          ? {
              valid: true,
              items: [
                {
                  name: '文档',
                  transport: 'http',
                  auth_mode: 'organization',
                  credential_count: 1,
                  has_credentials: true,
                  error: null,
                },
              ],
            }
          : { items: [service] }
      )
    )
    vi.stubGlobal('fetch', fetcher)
    const { page, client } = await screen(<ImportDialog close={() => {}} />)
    const raw = {
      mcpServers: {
        文档: {
          url: 'https://example.com/mcp',
          headers: { Authorization: 'Bearer test-import-secret' },
        },
      },
    }
    await userEvent.fill(page.getByLabelText('配置 JSON'), JSON.stringify(raw))
    await userEvent.click(page.getByRole('button', { name: '预览配置' }))
    await expect
      .element(page.getByRole('button', { name: '确认导入 1 个服务' }))
      .toBeVisible()
    await expect
      .element(page.getByText('test-import-secret', { exact: false }))
      .not.toBeInTheDocument()
    expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
      '/api/v1/mcp/import/preview',
    ])
    await userEvent.click(
      page.getByRole('button', { name: '确认导入 1 个服务' })
    )
    await expect.poll(() => fetcher.mock.calls.length).toBe(3)
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/mcp/import')
    expect(fetcher.mock.calls[2][0]).toBe(
      '/api/v1/mcp/services/service/discover'
    )
    expect(JSON.parse(String(fetcher.mock.calls[1][1].body))).toEqual({
      configuration: raw,
    })
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data)
      )
    ).not.toContain('test-import-secret')
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
  it('空编辑器保持简洁，主动填入示例后才出现可编辑 JSON', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<ImportDialog close={() => {}} />)
    const editor = page.getByRole('textbox', { name: '配置 JSON' })
    await expect
      .element(page.getByText('在此粘贴 MCP 配置 JSON…'))
      .toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '格式化' }))
      .toBeDisabled()
    await userEvent.click(page.getByRole('button', { name: '填入示例' }))
    await expect
      .poll(() => editor.element().textContent)
      .toContain('"mcpServers"')
    await expect
      .element(page.getByRole('button', { name: '填入示例' }))
      .not.toBeInTheDocument()
    await expect.element(editor).toHaveFocus()
    expect(fetcher).not.toHaveBeenCalled()
    await userEvent.fill(editor, '{"mcpServers":{}}')
    await expect
      .element(page.getByRole('button', { name: '填入示例' }))
      .not.toBeInTheDocument()
  })
  it('JSON 格式化保留内容，非法输入不会覆盖或发送配置', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<ImportDialog close={() => {}} />)
    const editor = page.getByRole('textbox', { name: '配置 JSON' })
    const raw = { mcpServers: { 文档: { url: 'https://example.com/mcp' } } }
    await userEvent.fill(editor, JSON.stringify(raw))
    await userEvent.click(page.getByRole('button', { name: '格式化' }))
    await expect
      .poll(() => editor.element().textContent)
      .toContain('  "mcpServers": {')
    await userEvent.fill(editor, '{invalid')
    await userEvent.click(page.getByRole('button', { name: '格式化' }))
    await expect
      .element(page.getByText('JSON 格式无效，请检查括号、逗号和引号'))
      .toBeVisible()
    expect(editor.element().textContent).toBe('{invalid')
    expect(fetcher).not.toHaveBeenCalled()
    await userEvent.click(editor)
    await userEvent.keyboard('{Tab}')
    await expect
      .element(page.getByRole('button', { name: '取消', exact: true }))
      .toHaveFocus()
  })
  it('预览存在不支持的服务时禁止确认导入', async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        valid: false,
        items: [
          {
            name: '本地进程',
            transport: 'stdio',
            auth_mode: 'none',
            has_credentials: false,
            error: '当前不支持 STDIO',
          },
        ],
      })
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<ImportDialog close={() => {}} />)
    const original = '{"mcpServers":{"本地进程":{"command":"npx"}}}'
    await userEvent.fill(page.getByLabelText('配置 JSON'), original)
    await userEvent.click(page.getByRole('button', { name: '预览配置' }))
    await expect.element(page.getByText('当前不支持 STDIO')).toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '确认导入 1 个服务' }))
      .toBeDisabled()
    expect(fetcher).toHaveBeenCalledTimes(1)
    await userEvent.click(page.getByRole('button', { name: '返回修改' }))
    expect(
      page.getByRole('textbox', { name: '配置 JSON' }).element().textContent
    ).toBe(original)
  })
  it('展示预览不调用连接，保存只提交展示内容', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({})
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<Presentation service={service} />)
    await userEvent.fill(page.getByLabelText('显示名称'), '企业文档')
    await userEvent.fill(page.getByLabelText('简介'), '搜索和阅读企业文档')
    await userEvent.click(page.getByRole('button', { name: '添加示例' }))
    await userEvent.fill(
      page.getByLabelText('使用示例 1'),
      '总结上周的会议记录'
    )
    await userEvent.click(page.getByRole('button', { name: '预览连接器' }))
    await expect.element(page.getByRole('dialog')).toBeVisible()
    expect(fetcher).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(page.getByRole('button', { name: '保存展示设置' }))
    await expect.poll(() => fetcher.mock.calls.length).toBe(1)
    expect(fetcher.mock.calls[0][0]).toBe(
      '/api/v1/mcp/services/service/presentation'
    )
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual({
      display_name: '企业文档',
      description: '搜索和阅读企业文档',
      icon: '',
      examples: ['总结上周的会议记录'],
      version: 1,
    })
  })
})

describe('MCP 参数与发现回归', () => {
  it('表单与 JSON 同步，省略可选字段并保留显式 false、null、数组和对象', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({
        result: { content: [{ type: 'text', text: 'ok' }] },
        duration_ms: 9,
      })
    )
    vi.stubGlobal('fetch', fetcher)
    const complex: Capability = {
      ...tool,
      definition: {
        inputSchema: {
          type: 'object',
          properties: {
            a: { type: 'number' },
            flag: { type: 'boolean' },
            skip: { type: 'number' },
            note: { type: ['string', 'null'] },
            tags: { type: 'array', items: { type: 'string' } },
            details: {
              type: 'object',
              properties: { label: { type: 'string' } },
              required: ['label'],
            },
          },
          required: ['a', 'details'],
        },
      },
    }
    const { page } = await screen(
      <RunPanel service={service} item={complex} close={() => {}} />
    )
    await userEvent.fill(page.getByLabelText('a *', { exact: true }), '0')
    await userEvent.fill(
      page.getByLabelText('label *', { exact: true }),
      'nested'
    )
    await userEvent.click(page.getByRole('checkbox', { name: '传入 flag' }))
    await userEvent.click(page.getByRole('checkbox', { name: '传入 note' }))
    await userEvent.click(
      page.getByRole('checkbox', { name: 'note 设为 null' })
    )
    await userEvent.click(page.getByRole('checkbox', { name: '传入 tags' }))
    await userEvent.click(page.getByRole('button', { name: '添加 tags' }))
    await userEvent.fill(
      page.getByLabelText('tags[0] *', { exact: true }),
      'first'
    )
    await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
    await expect
      .element(page.getByLabelText('参数（JSON）'))
      .toHaveTextContent('nested')
    await userEvent.click(page.getByRole('tab', { name: '表单', exact: true }))
    await expect
      .element(page.getByLabelText('a *', { exact: true }))
      .toHaveValue(0)
    await expect
      .element(page.getByLabelText('tags[0] *', { exact: true }))
      .toHaveValue('first')
    await userEvent.click(
      page.getByRole('button', { name: '运行', exact: true })
    )
    await expect.element(page.getByText('执行成功 · 9 ms')).toBeVisible()
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body)).arguments).toEqual(
      {
        a: 0,
        details: { label: 'nested' },
        flag: false,
        note: null,
        tags: ['first'],
      }
    )
    await userEvent.click(
      page.getByRole('tab', { name: '原始 JSON', exact: true })
    )
    await expect
      .element(page.getByLabelText('运行结果 JSON'))
      .toHaveTextContent('content')
  })
  it('无效 JSON 阻止切回表单；运行失败保留输入，执行中阻止重复请求', async () => {
    let finish!: (value: Response) => void
    const fetcher = vi.fn(
      (_url: string, _options: RequestInit) =>
        new Promise<Response>((resolve) => {
          finish = resolve
        })
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(
      <RunPanel service={service} item={tool} close={() => {}} />
    )
    await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
    await userEvent.fill(page.getByLabelText('参数（JSON）'), '{')
    await userEvent.click(page.getByRole('tab', { name: '表单', exact: true }))
    await expect
      .element(page.getByRole('tab', { name: 'JSON', exact: true }))
      .toHaveAttribute('aria-selected', 'true')
    await expect
      .element(page.getByLabelText('参数（JSON）'))
      .toHaveTextContent('{')
    await userEvent.fill(page.getByLabelText('参数（JSON）'), '{"a": 2}')
    await userEvent.click(
      page.getByRole('button', { name: '运行', exact: true })
    )
    await expect
      .element(page.getByRole('button', { name: '执行中…' }))
      .toBeDisabled()
    expect(fetcher).toHaveBeenCalledTimes(1)
    finish(
      Response.json({ error: { message: '连接暂时不可用' } }, { status: 502 })
    )
    await expect.element(page.getByText('连接暂时不可用')).toBeVisible()
    await expect
      .element(page.getByLabelText('参数（JSON）'))
      .toHaveTextContent('2')
  })
  it('无参数工具发送空对象；复杂 Schema 保留 JSON 模式', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
      Response.json({
        result: {
          isError: true,
          content: [{ type: 'text', text: '上游业务错误' }],
        },
        duration_ms: 4,
      })
    )
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(
      <RunPanel
        service={service}
        item={{
          ...tool,
          definition: { inputSchema: { type: 'object' } },
        }}
        close={() => {}}
      />
    )
    await expect.element(page.getByText('此工具不需要任何参数。')).toBeVisible()
    await userEvent.click(
      page.getByRole('button', { name: '运行', exact: true })
    )
    await expect.element(page.getByText('工具执行失败 · 4 ms')).toBeVisible()
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body)).arguments).toEqual(
      {}
    )
    await page.unmount()
    const complex = await screen(
      <RunPanel
        service={service}
        item={{
          ...tool,
          definition: {
            inputSchema: {
              type: 'object',
              properties: {
                variant: { oneOf: [{ type: 'string' }, { type: 'number' }] },
              },
            },
          },
        }}
        close={() => {}}
      />
    )
    await expect
      .element(complex.page.getByRole('tab', { name: '表单', exact: true }))
      .toBeDisabled()
    await expect
      .element(complex.page.getByLabelText('参数（JSON）'))
      .toBeVisible()
  })
})

it('导入后的发现失败仍完成配置保存，缺少个人凭据的服务不会借用连接', async () => {
  const close = vi.fn()
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/preview'))
      return Response.json({
        valid: true,
        items: [
          {
            name: 'public',
            transport: 'http',
            auth_mode: 'none',
            credential_count: 0,
            has_credentials: false,
            error: null,
          },
        ],
      })
    if (url.endsWith('/import'))
      return Response.json({
        items: [
          { ...service, id: 'public', auth_mode: 'none' },
          { ...service, id: 'personal', configured: false },
        ],
      })
    return Response.json(
      { error: { message: '读取能力失败' } },
      { status: 502 }
    )
  })
  vi.stubGlobal('fetch', fetcher)
  const { page } = await screen(<ImportDialog close={close} />)
  await userEvent.fill(
    page.getByLabelText('配置 JSON'),
    '{"mcpServers":{"public":{"url":"https://example.com/mcp"}}}'
  )
  await userEvent.click(page.getByRole('button', { name: '预览配置' }))
  await userEvent.click(page.getByRole('button', { name: '确认导入 1 个服务' }))
  await expect.poll(() => close.mock.calls.length).toBe(1)
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
    '/api/v1/mcp/import/preview',
    '/api/v1/mcp/import',
    '/api/v1/mcp/services/public/discover',
  ])
})

it('工具全选仅修改当前类别、保留说明覆盖；复制配置不携带凭据值', async () => {
  const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
    Response.json({
      items: [
        { ...tool, description: '自定义说明' },
        { ...tool, kind: 'prompts', key: 'prompt', name: 'prompt' },
      ],
    })
  )
  vi.stubGlobal('fetch', fetcher)
  const { page } = await screen(<ServiceCard service={service} />)
  await userEvent.click(page.getByRole('button', { name: '展开服务 协议测试' }))
  await userEvent.click(page.getByRole('button', { name: '全部开启' }))
  await expect
    .poll(
      () => fetcher.mock.calls.filter((c) => c[0].endsWith('/policy')).length
    )
    .toBe(1)
  const body = JSON.parse(
    String(fetcher.mock.calls.find((c) => c[0].endsWith('/policy'))![1].body)
  )
  expect(body).toEqual({
    kind: 'tools',
    key: 'sum',
    enabled: true,
    description: '自定义说明',
  })
  await userEvent.click(
    page.getByRole('button', { name: '更多服务操作 协议测试' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '复制配置 JSON' }))
  await expect.poll(() => copied.mock.calls.length).toBe(1)
  const configuration = JSON.parse(copied.mock.calls[0][0])
  expect(Object.keys(configuration)).toEqual(['services'])
  expect(configuration.services[0].credential_values).toBeUndefined()
  expect(configuration.services[0]).toMatchObject({
    name: service.name,
    enabled: false,
    url: service.url,
  })
})

it('运行替换行内定义区域，取消恢复焦点，结果留在工具条目内', async () => {
  const fetcher = vi.fn(async (url: string) =>
    Response.json(
      url.endsWith('/run')
        ? {
            result: { content: [{ type: 'text', text: 'inline-result' }] },
            duration_ms: 12,
          }
        : { items: [tool] }
    )
  )
  vi.stubGlobal('fetch', fetcher)
  const { page } = await screen(<Panel />)
  await userEvent.click(page.getByRole('button', { name: '展开 sum' }))
  await expect
    .element(page.getByText('能力定义 JSON', { exact: true }))
    .toBeVisible()
  expect(document.querySelectorAll('p[title="求和"]')).toHaveLength(1)
  await userEvent.click(page.getByRole('button', { name: '运行', exact: true }))
  await expect
    .element(page.getByRole('region', { name: '运行 sum' }))
    .toBeVisible()
  await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
  await expect
    .element(page.getByText('能力定义 JSON', { exact: true }))
    .not.toBeInTheDocument()
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/run'))).toBe(false)
  await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
  await userEvent.fill(page.getByLabelText('参数（JSON）'), '{"a":7}')
  const panel = page.getByRole('region', { name: '运行 sum' })
  await userEvent.click(
    panel.getByRole('button', { name: '运行', exact: true })
  )
  await expect.element(panel.getByText('inline-result')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '收起 sum' }))
  await userEvent.click(page.getByRole('button', { name: '运行', exact: true }))
  await expect.element(panel.getByText('inline-result')).toBeVisible()
  await userEvent.click(panel.getByRole('button', { name: '取消' }))
  await expect
    .element(page.getByRole('button', { name: '运行', exact: true }))
    .toHaveFocus()
  await userEvent.click(page.getByRole('button', { name: '展开 sum' }))
  await expect
    .element(page.getByText('能力定义 JSON', { exact: true }))
    .toBeVisible()
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith('/run'))
  ).toHaveLength(1)
})

it('数量精简为纯数字，千以上使用 k', async () => {
  expect([0, 999, 1000, 1250, 2299].map(shortTokens)).toEqual([
    '0',
    '999',
    '1k',
    '1.3k',
    '2.3k',
  ])
  const { page } = await screen(<TokenEstimate count={229} total={1200} />)
  await expect
    .element(page.getByLabelText('工具定义 Token 估算'))
    .toHaveTextContent('229 / 1.2k')
  expect(page.getByLabelText('工具定义 Token 估算').element().textContent).toBe(
    '229 / 1.2k'
  )
})

const deepWikiDefinition = {
  name: 'ask_wiki_question',
  description:
    "Ask any question about a GitHub repository's codebase and get an AI-powered answer\ngrounded in its DeepWiki.",
  inputSchema: {
    properties: {
      repoName: {
        anyOf: [
          {
            type: 'string',
          },
          {
            items: {
              type: 'string',
            },
            type: 'array',
          },
        ],
        description:
          'GitHub repository or list of repositories (max 10) in owner/repo format.',
      },
      question: {
        description: 'The question to ask about the repository.',
        type: 'string',
      },
    },
    required: ['repoName', 'question'],
    type: 'object',
  },
  outputSchema: {
    properties: {
      result: {
        type: 'string',
      },
    },
    required: ['result'],
    type: 'object',
    'x-fastmcp-wrap-result': true,
  },
  _meta: {
    _fastmcp: {
      tags: [],
    },
  },
}

it('DeepWiki 实际 anyOf 定义默认表单，仓库文本和列表可切换并提交正确类型', async () => {
  const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
    Response.json({ result: { content: [] }, duration_ms: 1 })
  )
  vi.stubGlobal('fetch', fetcher)
  const { page } = await screen(
    <RunPanel
      service={service}
      item={{
        ...tool,
        name: 'ask_wiki_question',
        definition: deepWikiDefinition,
      }}
      close={() => {}}
    />
  )
  await expect
    .element(page.getByRole('tab', { name: '表单', exact: true }))
    .toHaveAttribute('data-state', 'active')
  await userEvent.fill(
    page.getByRole('textbox', { name: 'repoName *', exact: true }),
    'facebook/react'
  )
  await userEvent.fill(
    page.getByRole('textbox', { name: 'question *', exact: true }),
    'How do hooks work?'
  )
  await userEvent.click(page.getByRole('button', { name: '运行', exact: true }))
  await expect.poll(() => fetcher.mock.calls.length).toBe(1)
  expect(JSON.parse(String(fetcher.mock.calls[0][1].body)).arguments).toEqual({
    repoName: 'facebook/react',
    question: 'How do hooks work?',
  })
  await userEvent.click(
    page.getByRole('combobox', { name: 'repoName 输入类型' })
  )
  await userEvent.click(page.getByRole('option', { name: '列表', exact: true }))
  await userEvent.click(page.getByRole('button', { name: '添加 repoName' }))
  await userEvent.fill(
    page.getByRole('textbox', { name: 'repoName[0] *', exact: true }),
    'facebook/react'
  )
  await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
  await expect
    .element(page.getByLabelText('参数（JSON）'))
    .toHaveTextContent('facebook/react')
  await userEvent.click(page.getByRole('tab', { name: '表单', exact: true }))
  await expect
    .element(page.getByRole('combobox', { name: 'repoName 输入类型' }))
    .toHaveTextContent('列表')
  await userEvent.click(page.getByRole('button', { name: '运行', exact: true }))
  await expect.poll(() => fetcher.mock.calls.length).toBe(2)
  expect(
    JSON.parse(String(fetcher.mock.calls[1][1].body)).arguments.repoName
  ).toEqual(['facebook/react'])
  await userEvent.click(page.getByRole('tab', { name: 'JSON', exact: true }))
  await userEvent.fill(
    page.getByLabelText('参数（JSON）'),
    '{"repoName":7,"question":"test"}'
  )
  await userEvent.click(page.getByRole('tab', { name: '表单', exact: true }))
  await expect
    .element(page.getByRole('tab', { name: 'JSON', exact: true }))
    .toHaveAttribute('data-state', 'active')
  await expect
    .element(page.getByText('参数 repoName 不符合可选输入类型'))
    .toBeVisible()
})

it('点击服务和工具标题展开，嵌套按钮与表单不误触，保留键盘展开', async () => {
  const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
    Response.json({ items: [tool] })
  )
  vi.stubGlobal('fetch', fetcher)
  const { page } = await screen(<ServiceCard service={service} />)
  await userEvent.click(page.getByText('协议测试', { exact: true }))
  const serviceArrow = page.getByRole('button', { name: '收起服务 协议测试' })
  await expect.element(serviceArrow).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(page.getByText('sum', { exact: true }))
  await expect
    .element(page.getByText('能力定义 JSON', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '复制工具名称 sum' }))
    .not.toBeInTheDocument()
  await userEvent.click(page.getByText('求和', { exact: true }))
  const arrow = page.getByRole('button', { name: '展开 sum' })
  await expect.element(arrow).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(page.getByRole('switch', { name: '启用 sum' }))
  await expect.element(arrow).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(page.getByRole('button', { name: '更多能力操作 sum' }))
  await userEvent.click(
    page.getByRole('menuitem', { name: '编辑说明', exact: true })
  )
  await expect
    .element(page.getByRole('dialog', { name: '编辑能力说明' }))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '取消', exact: true }))
  await expect.element(arrow).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(page.getByRole('button', { name: '运行', exact: true }))
  await expect
    .element(page.getByRole('region', { name: '运行 sum' }))
    .toBeVisible()
  await userEvent.fill(page.getByRole('spinbutton', { name: 'a *' }), '7')
  await expect
    .element(page.getByRole('region', { name: '运行 sum' }))
    .toBeVisible()
  await expect.element(serviceArrow).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(page.getByText('协议测试', { exact: true }))
  const collapsedServiceArrow = page.getByRole('button', {
    name: '展开服务 协议测试',
  })
  collapsedServiceArrow.element().focus()
  await userEvent.keyboard('{Enter}')
  await expect
    .element(page.getByRole('button', { name: '收起服务 协议测试' }))
    .toHaveAttribute('aria-expanded', 'true')
})

function ImportBackgroundHarness() {
  const [importing, setImporting] = useState(true)
  const { key } = useMcp()
  const services = useQuery({
    queryKey: [...key, 'services'],
    queryFn: async () =>
      (await fetch('/api/v1/mcp/services')).json() as Promise<{
        items: Service[]
      }>,
  })
  return (
    <>
      {services.data?.items.map((s) => (
        <ServiceCard key={s.id} service={s} />
      ))}
      {importing && <ImportDialog close={() => setImporting(false)} />}
    </>
  )
}
it.each([false, true])(
  '导入立即返回卡片，连接期间可展开，完成后就地显示结果（失败=%s）',
  async (failure) => {
    let saved = false
    let finished = false
    let finish!: () => void
    const waiting = new Promise<void>((resolve) => {
      finish = resolve
    })
    const imported = {
      ...service,
      auth_mode: 'none' as const,
      credential_fields: [],
      checked_at: null,
      counts: {},
    }
    const fetcher = vi.fn(async (url: string) => {
      if (url.endsWith('/preview'))
        return Response.json({
          valid: true,
          items: [
            {
              name: service.name,
              transport: 'http',
              auth_mode: 'none',
              has_credentials: false,
              credential_count: 0,
              error: null,
            },
          ],
        })
      if (url.endsWith('/import')) {
        saved = true
        return Response.json({ items: [imported] })
      }
      if (url.endsWith('/discover')) {
        await waiting
        finished = true
        return failure
          ? Response.json(
              { error: { message: '上游暂时不可用' } },
              { status: 502 }
            )
          : Response.json({
              items: [{ ...tool, enabled: true }],
              checked_at: service.checked_at,
              error: null,
            })
      }
      if (url.endsWith('/capabilities'))
        return Response.json({
          items: finished && !failure ? [{ ...tool, enabled: true }] : [],
          checked_at: finished && !failure ? service.checked_at : null,
          error: null,
        })
      return Response.json({
        items: saved
          ? [
              {
                ...imported,
                checked_at: finished && !failure ? service.checked_at : null,
                error: finished && failure ? '上游暂时不可用' : null,
              },
            ]
          : [],
      })
    })
    vi.stubGlobal('fetch', fetcher)
    const { page } = await screen(<ImportBackgroundHarness />)
    await userEvent.fill(
      page.getByLabelText('配置 JSON'),
      '{"mcpServers":{"test":{"url":"https://example.com/mcp"}}}'
    )
    await userEvent.click(page.getByRole('button', { name: '预览配置' }))
    await userEvent.click(
      page.getByRole('button', { name: '确认导入 1 个服务' })
    )
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    await expect
      .element(page.getByText('连接中', { exact: true }))
      .toBeVisible()
    await expect
      .element(page.getByRole('switch', { name: `启用服务 ${service.name}` }))
      .not.toBeChecked()
    await userEvent.click(
      page.getByRole('button', { name: `展开服务 ${service.name}` })
    )
    await expect
      .element(page.getByText('尚未读取能力，请在更多菜单中刷新工具'))
      .not.toBeInTheDocument()
    finish()
    await expect
      .element(page.getByText(failure ? '连接失败' : '已连接', { exact: true }))
      .toBeVisible()
    await expect
      .element(page.getByText('连接中', { exact: true }))
      .not.toBeInTheDocument()
    if (failure)
      await expect
        .element(page.getByText('上游暂时不可用', { exact: true }))
        .toBeVisible()
    else
      await expect
        .element(page.getByRole('switch', { name: '启用 sum' }))
        .toBeChecked()
    expect(
      fetcher.mock.calls.filter(([url]) => url.endsWith('/import'))
    ).toHaveLength(1)
  }
)
