import { useForm, useFormState } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
} from '@/components/ui/form'
import { Switch } from '@/components/ui/switch'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import {
  portalSchema,
  siteSettingsOptions,
} from '@/features/portal/site-settings'

type PortalSettings = Schema['PortalSettings']

export function PlatformPortalSettingsPage() {
  const settings = useQuery({
    queryKey: ['platform', 'portal'],
    queryFn: ({ signal }) =>
      api<PortalSettings>(
        '/platform/portal',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <PageShell title='门户设置'>
      {settings.isPending && <LoadingState />}
      {settings.isError && (
        <RequestError
          error={settings.error}
          retry={() => void settings.refetch()}
        />
      )}
      {!settings.isError && settings.data && (
        <PortalForm saved={settings.data} />
      )}
    </PageShell>
  )
}

function PortalForm({ saved }: { saved: PortalSettings }) {
  const { data: session } = useSession()
  const client = useQueryClient()
  const form = useForm<PortalSettings>({
    resolver: zodResolver(portalSchema),
    mode: 'onChange',
    defaultValues: saved,
  })
  const { isDirty, isValid } = useFormState({ control: form.control })
  const update = useMutation({
    mutationFn: (values: PortalSettings) =>
      api<PortalSettings>('/platform/portal', 'PUT', values, session?.csrf),
    onSuccess: (value) => {
      form.reset(value)
      client.setQueryData(['platform', 'portal'], value)
      client.setQueryData(siteSettingsOptions.queryKey, value)
      void client.invalidateQueries({ queryKey: siteSettingsOptions.queryKey })
      toast.success('门户设置已保存')
    },
  })
  const forbidden =
    update.error instanceof ApiError && [401, 403].includes(update.error.status)
  return (
    <Card className='w-full max-w-2xl'>
      <CardHeader>
        <CardTitle>首页展示</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form
            id='platform-portal-form'
            onSubmit={form.handleSubmit((value) => update.mutate(value))}
            className='flex flex-col gap-4'
          >
            <FormField
              control={form.control}
              name='portal_enabled'
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-4'>
                  <div className='flex flex-col gap-2'>
                    <FormLabel>开启门户首页</FormLabel>
                    <FormDescription>
                      关闭后，首页进入登录或后台；客户端下载页仍可公开访问。
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      onBlur={field.onBlur}
                      ref={field.ref}
                      disabled={update.isPending || forbidden}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            {update.isError && <RequestError error={update.error} />}
          </form>
        </Form>
      </CardContent>
      <CardFooter className='flex flex-wrap justify-between gap-3'>
        <Button asChild variant='outline'>
          <a href='/download'>查看下载页</a>
        </Button>
        <Button
          type='submit'
          form='platform-portal-form'
          disabled={update.isPending || forbidden || !isDirty || !isValid}
        >
          <Save data-icon='inline-start' />
          {update.isPending ? '保存中…' : '保存设置'}
        </Button>
      </CardFooter>
    </Card>
  )
}
