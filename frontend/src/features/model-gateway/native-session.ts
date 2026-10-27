import { bindNativeSession } from '@/vendor/newapi/lib/api'
import { ROLE } from '@/vendor/newapi/lib/roles'
import { useAuthStore } from '@/vendor/newapi/stores/auth-store'

export function bindNativeAdministrator(csrf: string, consoleUrl: string) {
  bindNativeSession(csrf, consoleUrl)
  // Presentation capabilities only. Every request independently requires the
  // active Actvero organization administrator and the configured native scope.
  useAuthStore.getState().auth.setUser({
    id: 0,
    username: 'actvero-organization-administrator',
    role: ROLE.ADMIN,
    permissions: {
      admin_permissions: {
        channel: {
          read: true,
          write: true,
          operate: true,
          sensitive_write: true,
        },
        task_plugin: { bind: true },
        option: { read: true, write: true },
      },
    },
  })
}
