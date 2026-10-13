import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, type RenderResult } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { SearchProvider } from '@/context/search-provider'

const COMMAND_MENU_PLACEHOLDER = '搜索页面或切换主题…'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  setTheme: vi.fn(),
  admin: true,
}))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    useLocation: () => false,
  }
})

vi.mock('@/context/theme-provider', () => ({
  useTheme: () => ({ setTheme: mocks.setTheme }),
}))

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({
    data: { organization: { role: mocks.admin ? 'administrator' : 'member' } },
  }),
}))

type ShortcutModifier = 'Control' | 'Meta'

async function renderWithSearchProvider() {
  return await render(<SearchProvider>{null}</SearchProvider>)
}

/**
 * Open the palette by shortcut, retrying while the keydown listener may not be mounted yet.
 * Waits between attempts so a successful toggle is not immediately undone by a second chord.
 */
async function openCommandPalette(
  screen: RenderResult,
  modifier: ShortcutModifier = 'Control'
) {
  await vi.waitFor(
    async () => {
      const isCommandPaletteOpen =
        document.querySelector(
          `[placeholder="${COMMAND_MENU_PLACEHOLDER}"]`
        ) !== null

      if (!isCommandPaletteOpen) {
        await userEvent.keyboard(`{${modifier}>}k{/${modifier}}`)
      }

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .toBeInTheDocument()
    },
    { interval: 50, timeout: 5000 }
  )
}

describe('SearchProvider and CommandMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.admin = true
  })

  it('renders the command palette when the palette is open', async () => {
    const screen = await renderWithSearchProvider()
    const { getByPlaceholder, getByText } = screen

    await openCommandPalette(screen)

    await expect
      .element(getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .toBeInTheDocument()
    await expect.element(getByText('主题')).toBeInTheDocument()
    await expect.element(getByText('浅色')).toBeInTheDocument()
    await expect.element(getByText('深色')).toBeInTheDocument()
    await expect.element(getByText('跟随系统')).toBeInTheDocument()
    await expect.element(getByText('成员管理')).toBeInTheDocument()
  })

  it('does not show the dialog content when search is closed', async () => {
    const { getByPlaceholder } = await renderWithSearchProvider()

    await expect
      .element(getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it.each([
    ['Ctrl', 'Control'],
    ['Cmd', 'Meta'],
  ] as const)(
    'opens the command menu when %s + K is pressed',
    async (_label, modifier) => {
      const screen = await renderWithSearchProvider()

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .not.toBeInTheDocument()

      await openCommandPalette(screen, modifier)

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .toBeInTheDocument()
    }
  )

  it('navigates to a top-level route and closes the palette when a nav item is selected', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByText('操作记录'))

    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/audit' })
    await expect
      .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('does not expose administrator commands to ordinary members', async () => {
    mocks.admin = false
    const screen = await renderWithSearchProvider()
    await openCommandPalette(screen)
    await expect.element(screen.getByText('成员管理')).not.toBeInTheDocument()
    await expect.element(screen.getByText('操作记录')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('option', { name: '个人设置' }))
    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/account' })
  })

  it('applies theme and closes the palette when a theme command is chosen', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByText('深色'))

    expect(mocks.setTheme).toHaveBeenCalledWith('dark')
    await expect
      .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('shows empty state when the filter matches nothing', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.fill(
      screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER),
      'zzzz-no-match-xxxx'
    )

    await expect
      .element(screen.getByText('没有找到匹配页面'))
      .toBeInTheDocument()
  })
})
