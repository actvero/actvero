import { useEffect, useState } from 'react'
import { Logo } from '@/assets/logo'
import { cn } from '@/lib/utils'
import { useBranding, type Branding } from './data'

function Artwork({
  light,
  dark,
  name,
  className,
  tone,
}: {
  light: string
  dark?: string
  name: string
  className?: string
  tone?: 'light' | 'dark'
}) {
  const [failed, setFailed] = useState<string[]>([])
  const failedLight = failed.includes(light)
  const hasDark = dark && !failed.includes(dark)
  if (failedLight)
    return (
      <span
        title={name}
        className={cn(
          'inline-flex min-w-0 items-center text-sm font-medium',
          className
        )}
      >
        <span className='truncate'>{name}</span>
      </span>
    )
  return (
    <span
      className={cn(
        'brand-artwork inline-flex items-center justify-center',
        !hasDark && 'brand-artwork-backed',
        className
      )}
    >
      {tone ? (
        <img
          src={tone === 'dark' && dark && !failed.includes(dark) ? dark : light}
          alt={name}
          className='max-h-full max-w-full object-contain'
          onError={() =>
            setFailed((items) => [
              ...items,
              tone === 'dark' && dark ? dark : light,
            ])
          }
        />
      ) : (
        <>
          <img
            src={light}
            alt={name}
            className={cn(
              'max-h-full max-w-full object-contain',
              dark && 'dark:hidden'
            )}
            onError={() => setFailed((items) => [...items, light])}
          />
          {dark && (
            <img
              src={failed.includes(dark) ? light : dark}
              alt={name}
              className='hidden max-h-full max-w-full object-contain dark:block'
              onError={() => setFailed((items) => [...items, dark])}
            />
          )}
        </>
      )}
    </span>
  )
}

export function BrandMark({
  brand: supplied,
  className,
  tone,
}: {
  brand?: Branding
  className?: string
  tone?: 'light' | 'dark'
}) {
  const current = useBranding()
  const brand = supplied ?? current
  return brand.assets.mark_light ? (
    <Artwork
      key={brand.assets.mark_light}
      light={brand.assets.mark_light}
      dark={brand.assets.mark_dark}
      name={brand.name}
      tone={tone}
      className={cn('size-8 shrink-0', className)}
    />
  ) : (
    <Logo
      aria-label={brand.name}
      className={cn('size-8 shrink-0', className)}
    />
  )
}

export function BrandLockup({
  brand: supplied,
  className,
  tone,
}: {
  brand?: Branding
  className?: string
  tone?: 'light' | 'dark'
}) {
  const current = useBranding()
  const brand = supplied ?? current
  return brand.assets.wordmark_light ? (
    <Artwork
      key={brand.assets.wordmark_light}
      light={brand.assets.wordmark_light}
      dark={brand.assets.wordmark_dark}
      name={brand.name}
      tone={tone}
      className={cn('h-12 max-w-64', className)}
    />
  ) : (
    <span className={cn('inline-flex min-w-0 items-center gap-2.5', className)}>
      <span aria-hidden='true'>
        <BrandMark brand={brand} tone={tone} />
      </span>
      <span className='truncate font-semibold'>{brand.name}</span>
    </span>
  )
}

export function BrandHead() {
  const brand = useBranding()
  useEffect(() => {
    const apply = () => {
      const heading = document
        .querySelector(
          'main h1, main [role="heading"][aria-level="1"], #content h1'
        )
        ?.textContent?.trim()
      document.title =
        heading && heading !== brand.name
          ? `${heading} · ${brand.name}`
          : brand.name
    }
    apply()
    const observer = new MutationObserver(apply)
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
    })
    for (const [rel, href] of [
      ['icon', brand.favicon_url],
      ['apple-touch-icon', brand.apple_icon_url],
    ]) {
      let node = document.head.querySelector<HTMLLinkElement>(
        `link[rel="${rel}"]`
      )
      if (!node) {
        node = document.createElement('link')
        node.rel = rel
        document.head.append(node)
      }
      node.href = href
    }
    const description = document.querySelector('meta[name="description"]')
    description?.setAttribute('content', `${brand.name} · 统一 AI 能力管理平台`)
    return () => observer.disconnect()
  }, [brand.name, brand.favicon_url, brand.apple_icon_url])
  return null
}
