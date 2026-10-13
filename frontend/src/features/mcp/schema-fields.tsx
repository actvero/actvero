import { useId } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'
import {
  baseType,
  formVariants,
  fieldInitialValue,
  validateRequired,
  nullable,
  schemaDefaults,
  type InputSchema,
} from './schema-utils'

export function SchemaFields({
  schema,
  value,
  onChange,
  disabled,
}: {
  schema: InputSchema
  value: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
  disabled: boolean
}) {
  return (
    <div className='flex flex-col gap-5'>
      {Object.entries(schema.properties ?? {}).map(([name, s]) => (
        <SchemaField
          key={name}
          name={name}
          schema={s}
          value={
            Object.prototype.hasOwnProperty.call(value, name)
              ? value[name]
              : undefined
          }
          required={(schema.required ?? []).includes(name)}
          disabled={disabled}
          onChange={(v) => {
            const next = Object.fromEntries(
              Object.entries(value).filter(([k]) => k !== name)
            )
            if (v !== undefined)
              Object.defineProperty(next, name, {
                value: v,
                enumerable: true,
                configurable: true,
                writable: true,
              })
            onChange(next)
          }}
        />
      ))}
    </div>
  )
}
function SchemaField({
  name,
  schema: s,
  value,
  onChange,
  required,
  disabled,
}: {
  name: string
  schema: InputSchema
  value: unknown
  onChange: (v: unknown) => void
  required: boolean
  disabled: boolean
}) {
  const id = useId()
  const branches = formVariants(s)
  if (branches) {
    const selected = Math.max(
      0,
      branches.findIndex(
        (branch) =>
          value !== undefined && !validateRequired(branch, value, '', false)
      )
    )
    const names: Record<string, string> = {
      string: '文本',
      array: '列表',
      object: '对象',
      number: '数值',
      integer: '整数',
      boolean: '布尔值',
      null: '空值',
    }
    return (
      <div className='flex min-w-0 flex-col gap-3'>
        <div className='flex flex-wrap items-center gap-3'>
          <Label htmlFor={`${id}-type`}>{name} 输入类型</Label>
          <Select
            value={String(selected)}
            disabled={disabled}
            onValueChange={(v) =>
              onChange(fieldInitialValue(branches[Number(v)]))
            }
          >
            <SelectTrigger id={`${id}-type`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {branches.map((branch, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {names[baseType(branch)!]}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <SchemaField
          name={name}
          schema={branches[selected]}
          value={value}
          onChange={onChange}
          required={required}
          disabled={disabled}
        />
      </div>
    )
  }
  const t = baseType(s)
  const isNull = value === null
  const active = required || value !== undefined
  function empty() {
    return (
      schemaDefaults(s) ??
      (t === 'object'
        ? {}
        : t === 'array'
          ? []
          : t === 'boolean'
            ? false
            : t === 'string'
              ? ''
              : '')
    )
  }
  return (
    <div className='flex min-w-0 flex-col gap-2'>
      <div className='flex flex-wrap items-center gap-3'>
        <Label htmlFor={id}>
          {name}
          {required ? ' *' : '（可选）'}
        </Label>
        {!required && (
          <Label>
            <Checkbox
              aria-label={`传入 ${name}`}
              checked={active}
              disabled={disabled}
              onCheckedChange={(v) => onChange(v ? empty() : undefined)}
            />
            传入
          </Label>
        )}
        {nullable(s) && active && (
          <Label>
            <Checkbox
              aria-label={`${name} 设为 null`}
              checked={isNull}
              disabled={disabled}
              onCheckedChange={(v) => onChange(v ? null : empty())}
            />
            null
          </Label>
        )}
      </div>
      {s.description && (
        <p id={`${id}-help`} className='text-sm text-muted-foreground'>
          {s.description}
        </p>
      )}
      {active && t === 'null' && (
        <p className='text-sm text-muted-foreground'>当前值：null</p>
      )}
      {active &&
        !isNull &&
        (s.enum ? (
          <Select
            value={
              value === undefined
                ? ''
                : String(s.enum.findIndex((v) => v === value))
            }
            disabled={disabled}
            onValueChange={(v) => onChange(s.enum![Number(v)])}
          >
            <SelectTrigger id={id} aria-describedby={`${id}-help`}>
              <SelectValue placeholder='请选择' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {s.enum.map((v, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {String(v)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        ) : t === 'boolean' ? (
          <Select
            value={value === undefined ? '' : String(value)}
            disabled={disabled}
            onValueChange={(v) => onChange(v === 'true')}
          >
            <SelectTrigger id={id}>
              <SelectValue placeholder='请选择 true / false' />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value='true'>true</SelectItem>
                <SelectItem value='false'>false</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        ) : t === 'object' ? (
          <div className='border-s ps-4'>
            <SchemaFields
              schema={s}
              value={(value ?? {}) as Record<string, unknown>}
              disabled={disabled}
              onChange={onChange}
            />
          </div>
        ) : t === 'array' ? (
          <div className='flex flex-col gap-3 border-s ps-4'>
            {(Array.isArray(value) ? value : []).map((v, i, all) => (
              <div key={i} className='flex items-start gap-2'>
                <div className='min-w-0 flex-1'>
                  <SchemaField
                    name={`${name}[${i}]`}
                    schema={s.items!}
                    value={v}
                    onChange={(n) =>
                      onChange(all.map((old, index) => (index === i ? n : old)))
                    }
                    required
                    disabled={disabled}
                  />
                </div>
                <Button
                  type='button'
                  variant='ghost'
                  size='icon'
                  aria-label={`删除 ${name}[${i}]`}
                  disabled={disabled}
                  onClick={() =>
                    onChange(all.filter((_, index) => index !== i))
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={disabled}
              onClick={() =>
                onChange([
                  ...(Array.isArray(value) ? value : []),
                  schemaDefaults(s.items!) ??
                    (baseType(s.items!) === 'object'
                      ? {}
                      : baseType(s.items!) === 'array'
                        ? []
                        : baseType(s.items!) === 'boolean'
                          ? false
                          : baseType(s.items!) === 'string'
                            ? ''
                            : null),
                ])
              }
            >
              <Plus />
              添加 {name}
            </Button>
          </div>
        ) : (
          <Input
            id={id}
            aria-describedby={`${id}-help`}
            disabled={disabled}
            type={t === 'number' || t === 'integer' ? 'number' : 'text'}
            step={t === 'integer' ? 1 : 'any'}
            value={value === undefined ? '' : String(value)}
            onChange={(e) =>
              onChange(
                t === 'number' || t === 'integer'
                  ? e.target.value === ''
                    ? undefined
                    : e.target.valueAsNumber
                  : e.target.value
              )
            }
          />
        ))}
    </div>
  )
}
