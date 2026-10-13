import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { Toaster } from '@/components/ui/sonner'
import { NavigationProgress } from '@/components/navigation-progress'
import { SessionBoundary } from '@/features/auth/gate'
import { BrandHead } from '@/features/branding/brand'
import { GeneralError } from '@/features/errors/general-error'
import { NotFoundError } from '@/features/errors/not-found-error'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()(
  {
    component: () => (
      <>
        <NavigationProgress />
        <BrandHead />
        <SessionBoundary>
          <Outlet />
        </SessionBoundary>
        <Toaster />
      </>
    ),
    notFoundComponent: NotFoundError,
    errorComponent: GeneralError,
  }
)
