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
import { Textarea } from '@/components/ui/textarea'
import { MemberPicker } from '@/components/member-picker'
import { RequestError } from '@/components/request-state'
import { sameDepartmentGrants } from '@/features/departments/scope'
import {
  audiences,
  categories,
  useWorkbenches,
  type Audience,
  type Category,
  type Workbench,
} from './shared'

export function WorkbenchMetadataForm({ item }: { item: Workbench }) {
  const id = useId()
  const [name, setName] = useState(item.display_name)
  const [description, setDescription] = useState(item.description)
  const [category, setCategory] = useState(item.category)
  const { csrf, update } = useWorkbenches()
  const save = useMutation({
    mutationFn: (body: Schema['WorkbenchMetadata']) =>
      api<Workbench>(`/workbenches/${item.id}`, 'PUT', body, csrf),
    onSuccess: (value) => {
      update(value)
      toast.success('已保存基本资料')
    },
  })
  const dirty =
    name.trim() !== item.display_name ||
    description.trim() !== item.description ||
    category !== item.category
  return (
    <Card className='max-w-3xl'>
      <CardHeader>
        <CardTitle>基本资料</CardTitle>
        <CardDescription>这些资料适用于工作台的所有版本。</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (dirty && name.trim() && !save.isPending)
              save.mutate({
                display_name: name,
                description,
                category,
                revision: item.revision,
              })
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`${id}-name`}>名称</FieldLabel>
              <Input
                id={`${id}-name`}
                required
                maxLength={100}
                value={name}
                disabled={save.isPending}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={`${id}-category`}>分类</FieldLabel>
              <Select
                value={category}
                onValueChange={(value) => setCategory(value as Category)}
                disabled={save.isPending}
              >
                <SelectTrigger id={`${id}-category`} className='w-full sm:w-56'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {Object.entries(categories).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={`${id}-description`}>简介</FieldLabel>
              <Textarea
                id={`${id}-description`}
                rows={4}
                maxLength={1024}
                value={description}
                disabled={save.isPending}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
            {save.isError && <RequestError error={save.error} />}
            <div>
              <Button
                type='submit'
                disabled={!name.trim() || !dirty || save.isPending}
              >
                {save.isPending ? '正在保存…' : '保存资料'}
              </Button>
            </div>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}

export function WorkbenchScopeForm({ item }: { item: Workbench }) {
  const id = useId()
  const [audience, setAudience] = useState(item.audience)
  const [members, setMembers] = useState(item.member_ids)
  const [departments, setDepartments] = useState(item.department_grants ?? [])
  const { csrf, update } = useWorkbenches()
  const save = useMutation({
    mutationFn: (body: Schema['WorkbenchScope']) =>
      api<Workbench>(`/workbenches/${item.id}/scope`, 'PUT', body, csrf),
    onSuccess: (value) => {
      update(value)
      toast.success('已保存使用范围')
    },
  })
  const selected = audience === 'selected'
  const dirty =
    audience !== item.audience ||
    (selected &&
      (members.length !== item.member_ids.length ||
        members.some((member) => !item.member_ids.includes(member)) ||
        !sameDepartmentGrants(departments, item.department_grants ?? [])))
  const valid = !selected || members.length > 0 || departments.length > 0
  return (
    <Card className='max-w-3xl'>
      <CardHeader>
        <CardTitle>使用范围</CardTitle>
        <CardDescription>
          指定当前组织中可以使用已发布版本的成员。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (dirty && valid && !save.isPending)
              save.mutate({
                audience,
                member_ids: selected ? members : [],
                department_grants: selected ? departments : [],
                revision: item.revision,
              })
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`${id}-audience`}>授权对象</FieldLabel>
              <Select
                value={audience}
                onValueChange={(value) => setAudience(value as Audience)}
                disabled={save.isPending}
              >
                <SelectTrigger id={`${id}-audience`} className='w-full sm:w-56'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {Object.entries(audiences).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>管理员始终具有管理权限。</FieldDescription>
            </Field>
            {selected && (
              <MemberPicker
                departmentScope={{
                  value: departments,
                  onChange: setDepartments,
                }}
                value={members}
                onChange={setMembers}
                disabled={save.isPending}
                selectionLabel='工作台授权成员'
              />
            )}
            {save.isError && <RequestError error={save.error} />}
            <div>
              <Button
                type='submit'
                disabled={!dirty || !valid || save.isPending}
              >
                {save.isPending ? '正在保存…' : '保存使用范围'}
              </Button>
            </div>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
