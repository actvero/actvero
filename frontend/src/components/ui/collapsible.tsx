import * as CollapsiblePrimitive from '@radix-ui/react-collapsible'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from './button'
import { Separator } from './separator'

function Collapsible({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Root>) {
  return <CollapsiblePrimitive.Root data-slot='collapsible' {...props} />
}

function CollapsibleTrigger({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleTrigger>) {
  return (
    <CollapsiblePrimitive.CollapsibleTrigger
      data-slot='collapsible-trigger'
      {...props}
    />
  )
}

function CollapsibleContent({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleContent>) {
  return (
    <CollapsiblePrimitive.CollapsibleContent
      data-slot='collapsible-content'
      {...props}
    />
  )
}

function CollapsibleHeader({
  className,
  expandOnClick = false,
  onClick,
  ...props
}: React.ComponentProps<'div'> & { expandOnClick?: boolean }) {
  return (
    <div
      data-slot='collapsible-header'
      className={cn(
        'rounded-t-[inherit] transition-colors focus-within:bg-muted/50 hover:bg-muted/50 data-[state=closed]:rounded-b-[inherit]',
        expandOnClick && 'cursor-pointer',
        className
      )}
      onClick={(event) => {
        onClick?.(event)
        if (!expandOnClick || event.defaultPrevented) return
        const target = event.target
        if (
          !(target instanceof Element) ||
          !event.currentTarget.contains(target)
        )
          return
        // Keep controls independent, including clicks bubbling from menu portals.
        const control = target.closest(
          'button, a, input, textarea, select, [role=button], [role=switch], [role=menuitem], [tabindex], [data-no-collapse]'
        )
        if (control && event.currentTarget.contains(control)) return
        if (window.getSelection()?.toString()) return
        event.currentTarget
          .querySelector<HTMLButtonElement>('[data-slot=collapsible-trigger]')
          ?.click()
      }}
      {...props}
    />
  )
}

export {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
  CollapsibleHeader,
}

function CollapsibleSection({
  title,
  children,
  ...props
}: Omit<React.ComponentProps<typeof Collapsible>, 'title'> & {
  title: React.ReactNode
}) {
  return (
    <Collapsible
      {...props}
      className={cn(
        'overflow-hidden rounded-xl border bg-card text-card-foreground',
        props.className
      )}
    >
      <CollapsibleTrigger asChild>
        <Button
          type='button'
          variant='ghost'
          className='group h-auto w-full justify-between rounded-none px-4 py-3'
        >
          {title}
          <ChevronDown
            data-icon='inline-end'
            className='transition-transform group-data-[state=open]:rotate-180'
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <Separator />
        <div className='bg-muted/30 p-4'>{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export { CollapsibleSection }
