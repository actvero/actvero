import { useRef, type ReactNode } from 'react'
import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
} from 'motion/react'
import { cn } from '@/lib/utils'

export function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode
  className?: string
  delay?: number
}) {
  const reduced = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduced ? false : { opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{ duration: 0.65, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}

// Adapted from Magic UI's Magic Card (MIT). See public/notices/magic-ui.txt.
// Keep the cursor gradient; use Actvero tokens and the existing theme provider.
export function SpotlightCard({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  const x = useMotionValue(-500)
  const y = useMotionValue(-500)
  const reduced = useReducedMotion()
  const background = useMotionTemplate`radial-gradient(360px circle at ${x}px ${y}px, var(--portal-glow), transparent 80%)`
  return (
    <div
      className={cn(
        'relative isolate overflow-hidden rounded-2xl border bg-card',
        className
      )}
      onPointerMove={(event) => {
        if (reduced || event.pointerType !== 'mouse') return
        const rect = event.currentTarget.getBoundingClientRect()
        x.set(event.clientX - rect.left)
        y.set(event.clientY - rect.top)
      }}
      onPointerLeave={() => {
        x.set(-500)
        y.set(-500)
      }}
    >
      <motion.div
        aria-hidden
        className='pointer-events-none absolute inset-0'
        style={{ background }}
      />
      <div className='relative h-full'>{children}</div>
    </div>
  )
}

export function PreviewFrame({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'center center'],
  })
  const rotateX = useTransform(scrollYProgress, [0, 1], [9, 0])
  const scale = useTransform(scrollYProgress, [0, 1], [0.94, 1])
  return (
    <div ref={ref} className='relative [perspective:1600px]'>
      <div
        aria-hidden
        className='pointer-events-none absolute -inset-x-6 top-12 bottom-0 rounded-full bg-portal-glow blur-3xl'
      />
      <motion.div
        className='relative overflow-hidden rounded-2xl border border-border/80 bg-background shadow-[0_28px_90px_-28px_var(--portal-shadow)] sm:rounded-3xl'
        style={
          reduced
            ? undefined
            : { rotateX, scale, transformOrigin: 'center top' }
        }
      >
        {children}
      </motion.div>
    </div>
  )
}

export function SectionHeading({
  eyebrow,
  children,
  description,
}: {
  eyebrow: string
  children: ReactNode
  description?: string
}) {
  return (
    <div className='flex flex-col gap-4'>
      <p className='font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase'>
        {eyebrow}
      </p>
      <h2 className='text-3xl leading-tight font-semibold tracking-tight sm:text-4xl lg:text-[2.8rem]'>
        {children}
      </h2>
      {description && (
        <p className='max-w-xl text-base leading-8 text-muted-foreground'>
          {description}
        </p>
      )}
    </div>
  )
}
