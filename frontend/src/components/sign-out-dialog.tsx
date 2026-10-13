import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { AccountCard } from '@/components/account-card'
import { RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { useBranding } from '@/features/branding/data'

export function SignOutDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const brand = useBranding()
  const { data } = useSession()
  const client = useQueryClient()
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', 'POST', undefined, data?.csrf),
    onSuccess: async () => {
      await client.cancelQueries()
      client.clear()
      window.location.replace('/login')
    },
  })
  return (
    <AlertDialog
      open={open}
      onOpenChange={(value) => {
        if (!logout.isPending) onOpenChange(value)
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>退出登录？</AlertDialogTitle>
          <AlertDialogDescription>
            仅退出当前浏览器的 {brand.name}，其他应用不受影响。
          </AlertDialogDescription>
        </AlertDialogHeader>
        {data?.user && <AccountCard user={data.user} />}
        {logout.isError && <RequestError error={logout.error} />}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={logout.isPending}>
            取消
          </AlertDialogCancel>
          <Button disabled={logout.isPending} onClick={() => logout.mutate()}>
            {logout.isPending ? '正在退出…' : '退出登录'}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
