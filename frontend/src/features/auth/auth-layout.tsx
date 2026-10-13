import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { BrandLockup } from '@/features/branding/brand'

export function AuthLayout({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <main
      id='content'
      className='flex min-h-svh items-center justify-center p-4 sm:p-8'
    >
      <div className='flex w-full max-w-md flex-col gap-6'>
        <div className='flex justify-center'>
          <BrandLockup />
        </div>
        <Card>
          <CardHeader>
            <CardTitle role='heading' aria-level={1}>
              {title}
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-5'>{children}</CardContent>
        </Card>
        <Button asChild variant='link'>
          <a href='/download'>下载桌面客户端</a>
        </Button>
      </div>
    </main>
  )
}
