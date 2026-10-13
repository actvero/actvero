import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { Building2, Check, ChevronDown, ShieldCheck } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { useLayout } from '@/context/layout-provider'
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
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from '@/components/ui/sidebar'
import { PlatformLogo } from '@/components/platform-logo'
import { useSession } from '@/features/auth/session'
import { useBranding } from '@/features/branding/data'
import { navigation, platformNavigation } from './data/sidebar-data'
import { NavGroup } from './nav-group'
import { NavUser } from './nav-user'

export function AppSidebar() {
  const { collapsible, variant } = useLayout()
  const { data: session } = useSession()
  const pathname = useLocation({ select: (location) => location.pathname })
  const platform = pathname.startsWith('/platform/')
  const groups = platform
    ? platformNavigation()
    : navigation(session?.organization?.role === 'administrator')
  const organizations = session?.organizations ?? []
  const canSwitch = Boolean(
    session?.platform_operator || organizations.length > 1
  )
  return (
    <Sidebar collapsible={collapsible} variant={variant}>
      <SidebarHeader>
        <WorkspaceSwitcher
          session={session}
          platform={platform}
          enabled={canSwitch}
        />
      </SidebarHeader>
      <SidebarContent>
        {groups.map((group) => (
          <NavGroup key={group.title} {...group} />
        ))}
      </SidebarContent>
      <SidebarFooter>
        {session?.user && <NavUser user={session.user} />}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

function WorkspaceSwitcher({
  session,
  platform,
  enabled,
}: {
  session: Schema['SessionView'] | undefined
  platform: boolean
  enabled: boolean
}) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const organizations = session?.organizations ?? []
  const switchWorkspace = useMutation({
    mutationFn: (tenantId: string | null) =>
      api<Schema['Message']>(
        '/auth/workspace',
        'POST',
        { tenant_id: tenantId },
        session?.csrf
      ),
    onSuccess: async (_, tenantId) => {
      await client.invalidateQueries({ queryKey: ['session'] })
      await navigate({ to: tenantId ? '/users' : '/platform/organizations' })
    },
  })
  const brand = useBranding()
  const title = platform
    ? brand.name
    : (session?.organization?.name ?? '选择组织')
  const description = platform
    ? '平台管理'
    : session?.platform_operator
      ? '平台运营'
      : session?.organization?.role === 'administrator'
        ? '组织管理员'
        : '组织成员'
  const button = (
    <SidebarMenuButton
      size='lg'
      tooltip={title}
      aria-label={`${title} ${description}`}
    >
      <div
        aria-hidden='true'
        className='flex size-8 shrink-0 items-center justify-center'
      >
        <PlatformLogo url={session?.platform_logo_url} />
      </div>
      <span className='grid min-w-0 flex-1 text-start leading-tight group-data-[collapsible=icon]:hidden'>
        <span className='truncate font-semibold'>{title}</span>
        <span className='truncate text-xs text-muted-foreground'>
          {description}
        </span>
      </span>
      {enabled && (
        <ChevronDown className='ms-auto group-data-[collapsible=icon]:hidden' />
      )}
    </SidebarMenuButton>
  )
  if (!enabled)
    return (
      <SidebarMenu>
        <SidebarMenuItem>{button}</SidebarMenuItem>
      </SidebarMenu>
    )
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>{button}</DropdownMenuTrigger>
          <DropdownMenuContent align='start' className='w-72'>
            <DropdownMenuLabel>切换工作空间</DropdownMenuLabel>
            <DropdownMenuGroup>
              {session?.platform_operator && (
                <DropdownMenuItem
                  onSelect={() => switchWorkspace.mutate(null)}
                  disabled={platform || switchWorkspace.isPending}
                >
                  <ShieldCheck />
                  <span className='flex flex-1 flex-col'>
                    <span>平台管理</span>
                  </span>
                  {platform && <Check className='ms-auto' />}
                </DropdownMenuItem>
              )}
            </DropdownMenuGroup>
            {!!organizations.length && <DropdownMenuSeparator />}
            <DropdownMenuGroup>
              {organizations.map((organization) => {
                const active =
                  !platform &&
                  session?.organization?.tenant_id === organization.tenant_id
                return (
                  <DropdownMenuItem
                    key={organization.tenant_id}
                    onSelect={() =>
                      switchWorkspace.mutate(organization.tenant_id)
                    }
                    disabled={active || switchWorkspace.isPending}
                  >
                    <Building2 />
                    <span className='flex flex-1 flex-col'>
                      <span>{organization.name}</span>
                      <span className='text-xs text-muted-foreground'>
                        {session?.platform_operator
                          ? '平台运营'
                          : organization.role === 'administrator'
                            ? '组织管理员'
                            : '组织成员'}
                      </span>
                    </span>
                    {active && <Check className='ms-auto' />}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
