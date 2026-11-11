import { useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { RequestError } from '@/components/request-state'
import {
  statuses,
  useWorkbenches,
  type Workbench,
  type WorkbenchVersion,
} from './shared'

export function WorkbenchRuntimeConfig({ item }: { item: Workbench }) {
  const id = useId()
  const [selectedId, setSelectedId] = useState<string>()
  const selected =
    item.versions.find((version) => version.id === selectedId) ??
    item.versions.find(
      (version) =>
        version.status === 'draft' && version.config_fields.length > 0
    ) ??
    item.versions.find((version) => version.status === 'published') ??
    item.versions[0]
  return (
    <Card className='max-w-3xl'>
      <CardHeader>
        <CardTitle>运行配置</CardTitle>
        <CardDescription>
          当前组织的成员运行此工作台时会读取这里的配置。填写服务地址等非敏感参数。
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-6'>
        {selected && (
          <Field>
            <FieldLabel htmlFor={id}>查看版本</FieldLabel>
            <Select value={selected.id} onValueChange={setSelectedId}>
              <SelectTrigger id={id} className='w-full sm:w-56'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {item.versions.map((version) => (
                    <SelectItem key={version.id} value={version.id}>
                      {version.version} · {statuses[version.status]}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        )}
        {selected?.config_fields.length ? (
          <ConfigForm key={selected.id} item={item} version={selected} />
        ) : (
          <p className='text-sm text-muted-foreground'>
            {selected
              ? '该版本未声明运行配置项。'
              : '上传工作台版本后可查看包内声明的配置项。'}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function ConfigForm({
  item,
  version,
}: {
  item: Workbench
  version: WorkbenchVersion
}) {
  const id = useId()
  const { csrf, update } = useWorkbenches()
  const [draft, setDraft] = useState<{
    revision: number
    values: Record<string, string>
  }>()
  const values = draft?.values ?? item.config_values
  const retired = version.status === 'withdrawn'
  const changed = version.config_fields.some(
    (field) =>
      (values[field.key]?.trim() || '') !==
      (item.config_values[field.key] || '')
  )
  const save = useMutation({
    mutationFn: (body: Schema['WorkbenchConfigUpdate']) =>
      api<Workbench>(
        `/workbenches/${item.id}/runtime-config`,
        'PUT',
        body,
        csrf
      ),
    onSuccess: (result) => {
      update(result)
      setDraft(undefined)
      toast.success('已保存运行配置')
    },
  })
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (!draft || !changed || retired || save.isPending) return
        save.mutate({
          revision: draft.revision,
          version_id: version.id,
          values: Object.fromEntries(
            version.config_fields.map((field) => [
              field.key,
              values[field.key]?.trim() ?? '',
            ])
          ),
        })
      }}
    >
      <FieldGroup>
        {version.config_fields.map((field) => {
          const inputId = `${id}-${field.key}`
          return (
            <Field key={field.key}>
              <FieldLabel htmlFor={inputId}>
                {field.label}
                {field.required && (
                  <span className='text-xs text-muted-foreground'>必填</span>
                )}
              </FieldLabel>
              <Input
                id={inputId}
                type={field.kind === 'url' ? 'url' : 'text'}
                value={values[field.key] ?? ''}
                placeholder={field.default ?? undefined}
                maxLength={2048}
                autoComplete='off'
                disabled={save.isPending || retired}
                aria-describedby={`${inputId}-help`}
                onChange={(event) => {
                  const value = event.target.value
                  setDraft((previous) => ({
                    revision: previous?.revision ?? item.revision,
                    values: {
                      ...(previous?.values ?? item.config_values),
                      [field.key]: value,
                    },
                  }))
                }}
              />
              <FieldDescription id={`${inputId}-help`} className='break-words'>
                <code>{field.key}</code>
                {field.description && ` · ${field.description}`}
                {field.default != null &&
                  ` · 留空时使用默认值 ${field.default}`}
              </FieldDescription>
            </Field>
          )
        })}
        {save.isError && <RequestError error={save.error} />}
        <div>
          <Button
            type='submit'
            disabled={!changed || retired || save.isPending}
          >
            {save.isPending ? '正在保存…' : '保存运行配置'}
          </Button>
        </div>
      </FieldGroup>
    </form>
  )
}
