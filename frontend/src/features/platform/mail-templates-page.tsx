import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'

const templates = [
  { value: 'organization_invitation', label: '组织开通邀请' },
  { value: 'member_invitation', label: '组织成员邀请' },
] as const

type Template = (typeof templates)[number]

function MailTemplatePreview({ template }: { template: Template }) {
  const preview = useQuery({
    queryKey: ['platform', 'mail-preview', template.value],
    queryFn: () =>
      api<Schema['MailTemplateView']>(
        `/platform/mail/preview?template=${template.value}`
      ),
  })

  if (preview.isPending) return <LoadingState />
  if (preview.isError)
    return (
      <RequestError
        error={preview.error}
        retry={() => void preview.refetch()}
      />
    )

  return (
    <Card>
      <CardContent className='flex flex-col gap-6'>
        <dl className='flex flex-wrap gap-x-4 gap-y-1 text-sm'>
          <dt className='text-muted-foreground'>邮件主题</dt>
          <dd>{preview.data.subject}</dd>
        </dl>
        <iframe
          title={`${template.label}邮件预览`}
          className='h-[560px] w-full rounded-lg border'
          sandbox=''
          srcDoc={preview.data.html}
        />
      </CardContent>
    </Card>
  )
}

export function PlatformMailTemplatesPage() {
  return (
    <PageShell title='邮件模板'>
      <Tabs defaultValue='organization_invitation' className='w-full max-w-4xl'>
        <TabsList variant='line'>
          {templates.map((template) => (
            <TabsTrigger key={template.value} value={template.value}>
              {template.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {templates.map((template) => (
          <TabsContent key={template.value} value={template.value}>
            <MailTemplatePreview template={template} />
          </TabsContent>
        ))}
      </Tabs>
    </PageShell>
  )
}
