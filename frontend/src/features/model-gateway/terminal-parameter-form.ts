import { z } from 'zod'
import type { Schema } from '@/lib/api'
import {
  chatPolicyInput,
  chatPolicyValues,
} from '@/features/model-catalog/chat-policy-form'
import {
  modelInput,
  modelSchema,
  reasoningValues,
  values,
} from '@/features/model-catalog/model-form'
import type { PublicationDraft } from './use-publication-preview'

const fields = modelSchema.shape
export const parameterSchema = z
  .object({
    capability_mode: z.enum(['auto', 'manual']),
    kind: fields.kind,
    context_window: fields.context_window,
    max_output: fields.max_output,
    capabilities: fields.capabilities,
    reasoning: fields.reasoning,
    chat_policy: fields.chat_policy,
    retrieval: fields.retrieval,
    image: fields.image,
    speech: fields.speech,
    transcription: fields.transcription,
  })
  .superRefine((value, ctx) => {
    if (value.kind === 'chat' && value.capability_mode === 'auto') return
    const parsed = modelSchema.safeParse({
      ...values(),
      ...value,
      name: 'model',
      slug: 'model',
    })
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        if (issue.path[0] && issue.path[0] in value)
          ctx.addIssue({
            code: 'custom',
            path: issue.path,
            message: issue.message,
          })
      }
    }
  })
export type ParameterValues = z.infer<typeof parameterSchema>
export type Parameters = Pick<
  PublicationDraft,
  | 'capability_mode'
  | 'kind'
  | 'context_window'
  | 'max_output'
  | 'capabilities'
  | 'reasoning_options'
  | 'chat_policy'
  | 'retrieval'
  | 'image'
  | 'speech'
  | 'transcription'
>

export function parameterValues(saved: Partial<Parameters>): ParameterValues {
  const defaults = values()
  return {
    capability_mode: saved.capability_mode ?? 'auto',
    kind: saved.kind ?? 'chat',
    context_window: saved.context_window?.toString() ?? '',
    max_output: saved.max_output?.toString() ?? '',
    capabilities: { ...defaults.capabilities, ...saved.capabilities },
    reasoning: reasoningValues(saved.reasoning_options),
    chat_policy: chatPolicyValues(saved.chat_policy as Schema['ChatPolicy']),
    retrieval: {
      ...defaults.retrieval,
      ...Object.fromEntries(
        Object.entries(saved.retrieval ?? {}).map(([key, value]) => [
          key,
          Array.isArray(value) ? value.join(',') : (value?.toString() ?? ''),
        ])
      ),
    },
    image: {
      ...defaults.image,
      ...saved.image,
      size: saved.image?.size ?? '',
      quality: saved.image?.quality ?? '',
      max_prompt_characters: String(saved.image?.max_prompt_characters ?? 2000),
    },
    speech: {
      ...defaults.speech,
      ...saved.speech,
      max_input_characters: String(saved.speech?.max_input_characters ?? 1000),
    },
    transcription: {
      ...defaults.transcription,
      ...saved.transcription,
      max_duration_seconds: String(
        saved.transcription?.max_duration_seconds ?? 120
      ),
    },
  }
}

export function parameterInput(value: ParameterValues): Parameters {
  // Reuse the existing parameter serialization; native routes and pricing are never sent.
  const input = modelInput({ ...values(), ...value })
  return {
    capability_mode: value.capability_mode,
    kind: value.kind,
    context_window: input.context_window,
    max_output: input.max_output,
    capabilities: input.capabilities,
    reasoning_options: input.reasoning_options,
    chat_policy: chatPolicyInput(value.chat_policy),
    retrieval: input.retrieval,
    image: input.image,
    speech: input.speech,
    transcription: input.transcription,
  }
}
