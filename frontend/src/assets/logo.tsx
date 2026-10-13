import { type SVGProps } from 'react'
import { cn } from '@/lib/utils'
import geometry from './brand/geometry.json'

export function Logo({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      data-actvero-brand='mark'
      viewBox={geometry.viewBox.join(' ')}
      xmlns='http://www.w3.org/2000/svg'
      height='24'
      width='24'
      fill='currentColor'
      className={cn('size-6', className)}
      {...props}
    >
      <title>Actvero</title>
      <path d={geometry.path} />
      <path d={geometry.path} transform={geometry.secondPartTransform} />
    </svg>
  )
}
