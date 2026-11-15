import { useId } from 'react'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Choice } from './controls'
import { chunkingError, chunkNumbers, type Chunking } from './shared'

const presets = [
  { value: 'smart', label: '按标题和段落' },
  { value: 'normal', label: '按固定长度' },
  { value: 'parent_child', label: '父子切片' },
] as const

export function ChunkFields({
  value,
  onChange,
}: {
  value: Chunking
  onChange: (value: Chunking) => void
}) {
  const id = useId()
  const parent = value.structure === 'parent_child'
  const fixed = value.mode === 'normal'
  const scheme = parent ? 'parent_child' : fixed ? 'normal' : 'smart'
  const issue = chunkingError(value)
  const input = (key: keyof typeof chunkNumbers, label: string) => (
    <Field key={key} data-invalid={issue?.key === key || undefined}>
      <FieldLabel htmlFor={id + key}>{label}</FieldLabel>
      <Input
        id={id + key}
        type='number'
        min={chunkNumbers[key].min}
        max={chunkNumbers[key].max}
        value={
          value[key] === 0 && key !== 'overlap_chars'
            ? ''
            : (value[key] ?? chunkNumbers[key].initial)
        }
        aria-invalid={issue?.key === key || undefined}
        aria-describedby={issue?.key === key ? id + 'error' : undefined}
        onChange={(event) => {
          const n = Number(event.target.value)
          onChange({
            ...value,
            [key]: n,
            ...(key === 'target_chars' && !parent
              ? { max_chars: Math.ceil(n * 1.5) }
              : {}),
            ...(key === 'max_chars' && parent && !fixed
              ? {
                  target_chars: Math.max(
                    100,
                    Math.min(6000, Math.floor(n / 1.5))
                  ),
                }
              : {}),
          })
        }}
      />
      {issue?.key === key && (
        <FieldError id={id + 'error'}>{issue.message}</FieldError>
      )}
    </Field>
  )
  return (
    <FieldGroup className='gap-4'>
      <FieldSet className='gap-2'>
        <FieldLegend variant='label' id={id + 'scheme'}>
          切片方案
        </FieldLegend>
        <RadioGroup
          variant='segmented'
          aria-labelledby={id + 'scheme'}
          value={scheme}
          onValueChange={(next) => {
            if (next === scheme) return
            onChange({
              structure: next === 'parent_child' ? 'parent_child' : 'general',
              mode: next === 'normal' ? 'normal' : 'smart',
              target_chars: 1200,
              max_chars: next === 'normal' ? 1000 : 1800,
              child_chars: 500,
              overlap_chars: 100,
            })
          }}
        >
          {presets.map((preset) => (
            <RadioGroupItem
              key={preset.value}
              variant='segmented'
              value={preset.value}
            >
              {preset.label}
            </RadioGroupItem>
          ))}
        </RadioGroup>
      </FieldSet>
      <FieldGroup className='grid grid-cols-2 gap-4'>
        {parent ? (
          <>
            {input('max_chars', '父片上限（字）')}
            {input('child_chars', '子片上限（字）')}
          </>
        ) : fixed ? (
          <>
            {input('max_chars', '切片长度（字）')}
            {input('overlap_chars', '重叠长度（字）')}
          </>
        ) : (
          input('target_chars', '每片约多少字')
        )}
      </FieldGroup>
      {(!fixed || parent) && (
        <Collapsible
          defaultOpen={
            parent
              ? fixed
              : (value.max_chars ?? 1800) !==
                Math.ceil((value.target_chars ?? 1200) * 1.5)
          }
        >
          <CollapsibleTrigger asChild>
            <Button variant='ghost' size='sm' type='button'>
              高级设置
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className='pt-3'>
            <FieldGroup className='gap-4'>
              {parent ? (
                <>
                  <Field>
                    <FieldLabel>父片切分方式</FieldLabel>
                    <Choice
                      label='父片切分方式'
                      value={value.mode ?? 'smart'}
                      onChange={(mode) =>
                        onChange({
                          ...value,
                          mode: mode as Chunking['mode'],
                          target_chars: Math.max(
                            100,
                            Math.min(
                              value.target_chars ?? 1200,
                              value.max_chars ?? 1800
                            )
                          ),
                          overlap_chars: Math.min(
                            value.overlap_chars ?? 100,
                            (value.child_chars ?? 350) - 1
                          ),
                        })
                      }
                      items={[
                        { value: 'smart', label: '按标题和段落' },
                        { value: 'normal', label: '按固定长度' },
                      ]}
                    />
                  </Field>
                  {fixed
                    ? input('overlap_chars', '子片重叠（字）')
                    : input('target_chars', '父片目标长度（字）')}
                </>
              ) : (
                input('max_chars', '段落合并软上限（字）')
              )}
            </FieldGroup>
          </CollapsibleContent>
        </Collapsible>
      )}
    </FieldGroup>
  )
}
