import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { ChevronsUpDown, Info, LogOut, UserRound } from 'lucide-react'
import type { Schema } from '@/lib/api'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { OpenSourceNoticesDialog } from '@/components/open-source-notices-dialog'
import { SignOutDialog } from '@/components/sign-out-dialog'
import { UserAvatar } from '@/components/user-avatar'

export function NavUser({ user }: { user: Schema['UserView'] }) {
  const [open, setOpen] = useState(false)
  const [noticesOpen, setNoticesOpen] = useState(false)
  const { isMobile } = useSidebar()
  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size='lg'
                aria-label={'账号菜单：' + user.name}
              >
                <UserAvatar user={user} />
                <div className='grid min-w-0 flex-1 text-start leading-tight group-data-[collapsible=icon]:hidden'>
                  <span className='truncate font-semibold'>{user.name}</span>
                  <span className='truncate text-xs'>{user.email}</span>
                </div>
                <ChevronsUpDown className='group-data-[collapsible=icon]:hidden' />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side={isMobile ? 'top' : 'right'}
              align='end'
              className='min-w-56'
            >
              <DropdownMenuLabel>{user.name}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem asChild>
                  <Link to='/account'>
                    <UserRound />
                    个人设置
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setNoticesOpen(true)}>
                  <Info />
                  开源声明
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem onSelect={() => setOpen(true)}>
                  <LogOut />
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
      <SignOutDialog open={open} onOpenChange={setOpen} />
      <OpenSourceNoticesDialog
        open={noticesOpen}
        onOpenChange={setNoticesOpen}
      />
    </>
  )
}
