import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Menu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { ThemeSwitch } from '@/components/theme-switch'
import { BrandLockup } from '@/features/branding/brand'
import { useBranding } from '@/features/branding/data'
import { siteSettingsOptions } from './site-settings'

export function PublicLayout({
  children,
  home = false,
  variant = 'default',
}: {
  children: ReactNode
  home?: boolean
  variant?: 'default' | 'download'
}) {
  const brand = useBranding()
  const download = variant === 'download'
  const settings = useQuery({ ...siteSettingsOptions, enabled: !home })
  // Portal availability only changes navigation; downloads never wait for it.
  const showPortal =
    home ||
    (!settings.isFetching && settings.isSuccess && settings.data.portal_enabled)
  const links = [
    ...(showPortal
      ? [
          [home ? '#product' : '/#product', '产品'],
          [home ? '#capabilities' : '/#capabilities', '能力'],
        ]
      : []),
    ['/download', '下载'],
  ]
  const [open, setOpen] = useState(false)
  return (
    <div
      className={cn(
        'relative min-h-svh bg-background text-foreground',
        download && 'flex flex-col'
      )}
    >
      <a
        href='#main'
        className='sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[100] focus:rounded-md focus:bg-background focus:p-3 focus:ring-2 focus:ring-ring'
      >
        跳转到内容
      </a>
      <header className='sticky top-0 z-40 border-b border-border/60 bg-background/85 backdrop-blur-xl'>
        <div
          className={cn(
            'mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6 lg:px-8',
            download && 'h-20 w-full max-w-[1408px] sm:h-24'
          )}
        >
          <a
            href='/'
            aria-label={`${brand.name} 首页`}
            className={cn(
              'flex items-center gap-2.5 rounded-sm font-manrope text-xl font-bold tracking-tight outline-ring focus-visible:ring-2',
              download && 'sm:text-3xl'
            )}
          >
            <BrandLockup />
          </a>
          <nav
            aria-label='主导航'
            className='hidden items-center gap-1 md:flex'
          >
            {links.map(([url, title]) => (
              <Button key={url} asChild variant='ghost'>
                <a
                  href={url}
                  aria-current={
                    download && url === '/download' ? 'page' : undefined
                  }
                  className='aria-[current=page]:underline aria-[current=page]:decoration-2 aria-[current=page]:underline-offset-8'
                >
                  {title}
                </a>
              </Button>
            ))}
          </nav>
          <div className='flex items-center gap-2'>
            <ThemeSwitch />
            <Button asChild size='sm'>
              <a href='/console'>登录</a>
            </Button>
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger asChild>
                <Button
                  variant='ghost'
                  size='icon'
                  className='md:hidden'
                  aria-label='打开导航'
                >
                  <Menu />
                </Button>
              </SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>{brand.name}</SheetTitle>
                  <SheetDescription className='sr-only'>
                    {showPortal
                      ? '浏览产品、能力和下载。'
                      : '下载客户端或进入控制台。'}
                  </SheetDescription>
                </SheetHeader>
                <nav className='flex flex-col gap-3 p-4' aria-label='移动导航'>
                  {links.map(([url, title]) => (
                    <Button key={url} asChild variant='ghost'>
                      <a
                        href={url}
                        aria-current={
                          download && url === '/download' ? 'page' : undefined
                        }
                        onClick={() => setOpen(false)}
                      >
                        {title}
                      </a>
                    </Button>
                  ))}
                  <Button asChild>
                    <a href='/console'>
                      进入控制台
                      <ArrowRight />
                    </a>
                  </Button>
                </nav>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>
      <main id='main' className={download ? 'flex-1' : undefined}>
        {children}
      </main>
      {download ? (
        <footer className='mx-6 border-t py-12 text-center text-sm text-muted-foreground sm:mx-12 lg:mx-24'>
          © {new Date().getFullYear()} {brand.name}
        </footer>
      ) : (
        <footer className='border-t bg-muted/20'>
          <div className='mx-auto flex max-w-6xl flex-col gap-6 px-6 py-9 sm:flex-row sm:items-center sm:justify-between lg:px-8'>
            <div>
              <a
                href='/'
                className='flex w-fit items-center gap-2 font-manrope font-bold'
              >
                <BrandLockup />
              </a>
              <p className='mt-3 text-xs text-muted-foreground'>
                让企业 AI，真正用起来。
              </p>
            </div>
            <div className='flex flex-wrap items-center gap-2'>
              <Button asChild variant='ghost' size='sm'>
                <a href='/download'>客户端下载</a>
              </Button>
              <Button asChild variant='ghost' size='sm'>
                <a href='/console'>
                  控制台
                  <ArrowRight />
                </a>
              </Button>
            </div>
          </div>
        </footer>
      )}
    </div>
  )
}
