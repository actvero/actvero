/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import { createContext, useContext } from 'react'
import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import { cn } from '@newapi/lib/utils'
import { tabsListStyles, tabsTriggerStyles } from '@/components/ui/tabs-styles'

type TabsVariant = 'default' | 'line'
const TabsVariantContext = createContext<TabsVariant>('default')

function Tabs({
  className,
  orientation = 'horizontal',
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot='tabs'
      orientation={orientation}
      data-orientation={orientation}
      className={cn(
        'group/tabs flex gap-2 data-horizontal:flex-col',
        className
      )}
      {...props}
    />
  )
}

const tabsListVariants = ({
  variant = 'default',
}: { variant?: TabsVariant } = {}) => tabsListStyles(variant)

function TabsList({
  className,
  variant = 'default',
  ...props
}: TabsPrimitive.List.Props & { variant?: TabsVariant }) {
  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.List
        data-slot='tabs-list'
        data-variant={variant}
        className={cn(
          tabsListVariants({ variant }),
          'group-data-vertical/tabs:h-auto group-data-vertical/tabs:flex-col',
          className
        )}
        {...props}
      />
    </TabsVariantContext.Provider>
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  const variant = useContext(TabsVariantContext)
  return (
    <TabsPrimitive.Tab
      data-slot='tabs-trigger'
      className={cn(
        tabsTriggerStyles(variant),
        'group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start',
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot='tabs-content'
      className={cn('flex-1 text-sm outline-none', className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
