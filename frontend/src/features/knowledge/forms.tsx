import { useId } from 'react'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { MemberPicker } from '@/components/member-picker'
import { Choice } from './controls'
import { KnowledgeIconField } from './icon'
import { type BaseInput, type Base } from './shared'

export function BaseFields({
  value,
  onChange,
  icon,
}: {
  value: BaseInput
  onChange: (v: BaseInput) => void
  icon?: Base['icon']
}) {
  const id = useId()
  return (
    <FieldGroup className='gap-5'>
      <div className='flex items-center gap-4'>
        <KnowledgeIconField
          name={value.name}
          value={value.icon_selection ?? icon}
          onChange={(selection) =>
            onChange({
              ...value,
              icon_selection: { key: '', image: '', ...selection },
            })
          }
        />
        <Field className='min-w-0 flex-1'>
          <FieldLabel htmlFor={id + 'name'}>知识库名称</FieldLabel>
          <Input
            id={id + 'name'}
            value={value.name}
            maxLength={100}
            required
            placeholder='例如：产品手册'
            onChange={(e) => onChange({ ...value, name: e.target.value })}
          />
        </Field>
      </div>
      <Field>
        <FieldLabel htmlFor={id + 'description'}>
          简介 <span className='font-normal text-muted-foreground'>选填</span>
        </FieldLabel>
        <Textarea
          id={id + 'description'}
          value={value.description ?? ''}
          maxLength={1000}
          placeholder='例如：产品功能、使用方式和常见问题'
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
      </Field>
      <Field>
        <FieldLabel>使用范围</FieldLabel>
        <Choice
          label='使用范围'
          value={value.audience ?? 'administrators'}
          onChange={(v) =>
            onChange({
              ...value,
              audience: v as BaseInput['audience'],
              member_ids: [],
              department_grants: [],
            })
          }
          items={[
            { value: 'administrators', label: '仅管理员' },
            { value: 'organization', label: '组织全员' },
            { value: 'selected', label: '指定部门与成员' },
          ]}
        />
        {value.audience === 'selected' && (
          <MemberPicker
            value={value.member_ids ?? []}
            onChange={(v) => onChange({ ...value, member_ids: v })}
            departmentScope={{
              value: value.department_grants ?? [],
              onChange: (v) => onChange({ ...value, department_grants: v }),
            }}
          />
        )}
      </Field>
    </FieldGroup>
  )
}
export { ChunkFields } from './chunk-fields'
