import { useFormContext, useWatch } from 'react-hook-form'
import { Button } from '@/components/ui/button'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ImageFields } from '@/features/model-catalog/image-fields'
import { capabilities, kinds } from '@/features/model-catalog/model-form'
import { ReasoningFields } from '@/features/model-catalog/reasoning-fields'
import { RetrievalFields } from '@/features/model-catalog/retrieval-fields'
import { SpeechFields } from '@/features/model-catalog/speech-fields'
import { TranscriptionFields } from '@/features/model-catalog/transcription-fields'
import type { ParameterValues } from './terminal-parameter-form'

export function TerminalParameters({
  resolved,
  onPrefill,
}: {
  resolved: boolean
  onPrefill: () => void
}) {
  const form = useFormContext<ParameterValues>()
  const { kind, capability_mode: mode } = useWatch({ control: form.control })
  return (
    <FieldGroup>
      <FieldSet>
        <FieldLegend>能力与限制</FieldLegend>
        {kind === 'chat' && (
          <>
            <FormField
              control={form.control}
              name='capability_mode'
              render={({ field }) => (
                <Field>
                  <FieldLabel htmlFor='terminal-parameter-mode'>
                    参数来源
                  </FieldLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger
                      id='terminal-parameter-mode'
                      className='w-full'
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value='auto'>自动识别</SelectItem>
                        <SelectItem value='manual'>管理员填写</SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </Field>
              )}
            />
            {mode === 'manual' && (
              <Button
                type='button'
                variant='outline'
                onClick={onPrefill}
                disabled={!resolved}
              >
                带入自动识别参数
              </Button>
            )}
          </>
        )}
        {kind !== 'chat' && (
          <FieldDescription>当前用途：{kinds[kind ?? 'chat']}</FieldDescription>
        )}
      </FieldSet>
      {kind === 'chat' ? (
        mode === 'manual' && (
          <>
            <FieldGroup className='grid gap-4 sm:grid-cols-2'>
              {(
                [
                  ['context_window', '上下文上限（Token）'],
                  ['max_output', '最大输出（Token）'],
                ] as const
              ).map(([name, label]) => (
                <FormField
                  key={name}
                  control={form.control}
                  name={name}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{label}</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          inputMode='numeric'
                          placeholder='未配置'
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))}
              {capabilities.map(([name, label]) => (
                <FormField
                  key={name}
                  control={form.control}
                  name={`capabilities.${name}`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{label}</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className='w-full'>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value='unknown'>未知</SelectItem>
                            <SelectItem value='supported'>支持</SelectItem>
                            <SelectItem value='unsupported'>不支持</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))}
            </FieldGroup>
            <ReasoningFields disabled={false} />
          </>
        )
      ) : kind === 'image_generation' ? (
        <ImageFields disabled={false} />
      ) : kind === 'speech' ? (
        <SpeechFields disabled={false} />
      ) : kind === 'transcription' ? (
        <TranscriptionFields disabled={false} />
      ) : (
        <RetrievalFields disabled={false} />
      )}
    </FieldGroup>
  )
}
