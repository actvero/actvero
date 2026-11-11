import { useFormContext, useWatch } from 'react-hook-form'
import {
  FieldDescription,
  FieldGroup,
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

const chatCapabilities = capabilities.filter(([name]) => name !== 'streaming')

export function TerminalParameters() {
  const form = useFormContext<ParameterValues>()
  const kind = useWatch({ control: form.control, name: 'kind' })
  return (
    <FieldGroup>
      <FieldSet>
        <FieldLegend>能力与限制</FieldLegend>
        {kind !== 'chat' && (
          <FieldDescription>当前用途：{kinds[kind]}</FieldDescription>
        )}
      </FieldSet>
      {kind === 'chat' ? (
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
                        placeholder='留空'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
            {chatCapabilities.map(([name, label]) => (
              <FormField
                key={name}
                control={form.control}
                name={`capabilities.${name}`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{label}</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value='unknown'>留空</SelectItem>
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
