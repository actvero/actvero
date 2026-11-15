import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { CreateKnowledge } from './create'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org', role: 'administrator' },
    user: { id: 'admin' },
    csrf: 'synthetic',
  }),
}))
afterEach(() => vi.unstubAllGlobals())

async function startCreation(beforeNext?: () => Promise<void>) {
  const onCreated = vi.fn()
  const create = vi.fn()
  const upload = vi.fn()
  const replaceIcon = vi.fn()
  const entry = {
    key: 'lucide:file-text',
    label: '文档',
    category: '办公',
    image:
      'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22/%3E',
  }
  vi.stubGlobal('fetch', async (url: RequestInfo, options?: RequestInit) => {
    if (String(url).endsWith('/icon-catalog')) return Response.json([entry])
    if (options?.method === 'PATCH') {
      const body = JSON.parse(String(options.body))
      replaceIcon(body)
      return Response.json({
        id: 'base-1',
        name: '产品资料',
        version: body.version + 1,
        icon: body.icon_selection,
      })
    }
    if (options?.method === 'POST') {
      if (String(url).includes('/documents?')) {
        upload(String(url), options.body)
        return Response.json({}, { status: 201 })
      }
      const body = JSON.parse(String(options.body))
      create(body)
      return Response.json(
        {
          id: 'base-1',
          name: body.name,
          version: 1,
          icon: body.icon_selection && {
            ...body.icon_selection,
            image: entry.image,
          },
        },
        { status: 201 }
      )
    }
    return Response.json({
      version: 3,
      models: [],
      credentials: [],
      rerank_enabled: false,
    })
  })
  await render(
    <QueryClientProvider client={new QueryClient()}>
      <CreateKnowledge onCreated={onCreated} />
    </QueryClientProvider>
  )
  await page.getByLabelText('知识库名称').fill('产品资料')
  await beforeNext?.()
  await page.getByRole('button', { name: '下一步' }).click()
  return { onCreated, create, upload, replaceIcon }
}

it('保存父子切片参数，并可跳过上传直达文档列表', async () => {
  const { onCreated, create, upload } = await startCreation()
  await page.getByRole('radio', { name: '父子切片' }).click()
  const child = page.getByLabelText('子片上限（字）')
  await child.fill('1800')
  const next = page.getByRole('button', { name: '创建并继续' })
  await expect.element(next).toBeDisabled()
  await expect.element(child).toHaveAttribute('aria-invalid', 'true')
  await child.fill('400')
  await next.click()
  await page.getByRole('button', { name: '跳过上传' }).click()
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({
      name: '产品资料',
      defaults_version: 3,
      chunking: expect.objectContaining({
        structure: 'parent_child',
        child_chars: 400,
      }),
    })
  )
  expect(upload).not.toHaveBeenCalled()
  expect(onCreated).toHaveBeenCalledExactlyOnceWith('base-1')
})

it('普通切片可上传文件后进入文档列表', async () => {
  const { create, onCreated, upload } = await startCreation()
  await page.getByRole('button', { name: '创建并继续' }).click()
  await userEvent.upload(
    page.getByLabelText('上传知识库文档'),
    new File(['知识资料'], 'handbook.txt')
  )
  await page.getByRole('button', { name: '进入文档' }).click()
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({
      chunking: expect.objectContaining({ structure: 'general' }),
    })
  )
  expect(upload).toHaveBeenCalledWith(
    expect.stringContaining('filename=handbook.txt'),
    expect.any(File)
  )
  expect(onCreated).toHaveBeenCalledExactlyOnceWith('base-1')
})

it('建库时选择图标，在导入页可以裁剪照片并更换头像', async () => {
  await page.viewport(390, 844)
  const add = page.getByRole('button', { name: '添加知识库头像' })
  const edit = page.getByRole('button', { name: '编辑知识库头像' })
  const picker = page.getByRole('dialog', { name: '选择知识库头像' })
  const apply = page.getByRole('button', { name: '使用此图标' })
  const { create, replaceIcon } = await startCreation(async () => {
    await add.click()
    await expect
      .element(picker.getByRole('tab', { name: '默认头像' }))
      .not.toBeInTheDocument()
    await expect.element(apply).toBeDisabled()
    await picker.getByRole('button', { name: '文档', exact: true }).click()
    await apply.click()
    await expect.element(picker).not.toBeInTheDocument()
  })
  await page.getByRole('button', { name: '创建并继续' }).click()
  await edit.click()
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({
      icon_selection: { source: 'library', key: 'lucide:file-text', image: '' },
    })
  )
  await picker.getByRole('tab', { name: '上传图片' }).click()
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 64
  const blob = await new Promise<Blob>((resolve) => {
    canvas.toBlob((image) => resolve(image!), 'image/png')
  })
  await userEvent.upload(
    page.getByLabelText('选择上传图标'),
    new File([blob], 'avatar.png', { type: 'image/png' })
  )
  await page.getByRole('button', { name: '应用裁剪' }).click()
  await expect.element(picker.getByText('已选：上传图片')).toBeVisible()
  await apply.click()
  await expect.element(picker).not.toBeInTheDocument()
  expect(replaceIcon).toHaveBeenCalledExactlyOnceWith({
    version: 1,
    icon_selection: {
      source: 'upload',
      key: '',
      image: expect.stringMatching(/^data:image\/webp;base64,/),
    },
  })
  await edit.click()
  await picker.getByRole('button', { name: '移除头像' }).click()
  await expect.element(picker).not.toBeInTheDocument()
  await expect.element(add).toBeVisible()
  expect(replaceIcon).toHaveBeenLastCalledWith({
    version: 2,
    icon_selection: { source: 'auto', key: '', image: '' },
  })
})
