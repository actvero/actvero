import { useId } from 'react'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { MemberPicker } from '@/components/member-picker'
import { Choice } from './controls'
import { type BaseInput, type Chunking } from './shared'

export function BaseFields({
  value,
  onChange,
}: {
  value: BaseInput
  onChange: (v: BaseInput) => void
}) {
  const id = useId()
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor={id + 'name'}>知识库名称</FieldLabel>
        <Input
          id={id + 'name'}
          value={value.name}
          maxLength={100}
          required
          placeholder='例如：产品手册、内部制度'
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor={id + 'description'}>用途说明</FieldLabel>
        <Textarea
          id={id + 'description'}
          value={value.description ?? ''}
          maxLength={1000}
          placeholder='这些资料用于回答哪些问题'
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
export function ChunkFields({
  value,
  onChange,
}: {
  value: Chunking
  onChange: (v: Chunking) => void
}) {
  const id = useId()
  const normal = value.mode === 'normal'
  const fields = normal
    ? ([
        ['max_chars', '切片长度（字）'],
        ['overlap_chars', '重叠长度（字）'],
      ] as const)
    : ([
        ['target_chars', '目标字数'],
        ['max_chars', '合并上限（字）'],
      ] as const)
  return (
    <FieldGroup>
      <Field>
        <FieldLabel>切片方式</FieldLabel>
        <Choice
          label='切片方式'
          value={value.mode ?? 'smart'}
          onChange={(v) =>
            onChange({
              ...value,
              mode: v as Chunking['mode'],
              target_chars: Math.min(
                value.target_chars ?? 1200,
                value.max_chars ?? 1800
              ),
            })
          }
          items={[
            { value: 'smart', label: '智能切片' },
            { value: 'normal', label: '长度切片' },
          ]}
        />
      </Field>
      <div className='grid gap-4 sm:grid-cols-2'>
        {fields.map(([key, label]) => (
          <Field key={key}>
            <FieldLabel htmlFor={id + key}>{label}</FieldLabel>
            <Input
              id={id + key}
              type='number'
              min={key === 'overlap_chars' ? 0 : 100}
              max={
                key === 'overlap_chars'
                  ? 1000
                  : key === 'target_chars'
                    ? 6000
                    : 10000
              }
              value={value[key] ?? 0}
              onChange={(e) =>
                onChange({
                  ...value,
                  [key]: Number(e.target.value),
                })
              }
            />
          </Field>
        ))}
      </div>
    </FieldGroup>
  )
}
