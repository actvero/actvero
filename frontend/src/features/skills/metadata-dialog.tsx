import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useReturnFocus } from '@/hooks/use-return-focus'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Form } from '@/components/ui/form'
import { RequestError } from '@/components/request-state'
import { metadataSchema, type Metadata } from './form-schema'
import { MetadataFields } from './metadata-fields'
import { useSkills, type Skill } from './shared'

export function MetadataDialog({
  skill,
  close,
}: {
  skill: Skill
  close: () => void
}) {
  const restoreFocus = useReturnFocus()
  const { csrf, refresh } = useSkills()
  const [error, setError] = useState<unknown>()
  const form = useForm<Metadata>({
    resolver: zodResolver(metadataSchema),
    defaultValues: {
      display_name: skill.display_name,
      description: skill.description,
      category: skill.category ?? 'uncategorized',
      audience: skill.audience,
      member_ids: skill.member_ids,
      icon_selection: skill.icon_selection ?? { source: 'auto' },
    },
  })
  const busy = form.formState.isSubmitting
  return (
    <Dialog open onOpenChange={(v) => !v && !busy && close()}>
      <DialogContent
        onCloseAutoFocus={restoreFocus}
        className='max-h-[90dvh] overflow-y-auto sm:max-w-xl'
      >
        <DialogHeader>
          <DialogTitle>技能设置</DialogTitle>
          <DialogDescription>
            调整展示资料与所有版本共用的使用范围。原始技能文件保持不变。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='space-y-5'
            onSubmit={form.handleSubmit(async (values) => {
              setError(undefined)
              try {
                await api(
                  `/skills/${skill.id}`,
                  'PUT',
                  { ...values, revision: skill.revision },
                  csrf
                )
                await refresh()
                toast.success('技能设置已保存')
                close()
              } catch (e) {
                setError(e)
              }
            })}
          >
            <MetadataFields
              form={form}
              disabled={busy}
              packageIcon={
                skill.versions.find(
                  (version) => version.id === skill.default_version_id
                )?.package_icon
              }
              iconWarning={
                skill.versions.find(
                  (version) => version.id === skill.default_version_id
                )?.icon_warning
              }
            />
            {error != null && <RequestError error={error} />}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                disabled={busy}
                onClick={close}
              >
                取消
              </Button>
              <Button disabled={busy}>{busy ? '保存中…' : '保存设置'}</Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
