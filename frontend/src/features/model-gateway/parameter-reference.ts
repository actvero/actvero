import {
  capabilities,
  effortLabels,
  reasoningValues,
} from '@/features/model-catalog/model-form'
import type { ReferenceModel } from '@/features/model-catalog/reference-models'
import type { ParameterValues } from './terminal-parameter-form'

export type PreviewRow = {
  label: string
  current?: string
  reference?: string
  action: '保留' | '填入' | '覆盖' | '留空' | '与已填参数冲突'
}

const numberLabel = (value: string | number) => Number(value).toLocaleString()

function reasoningLabel(value: ParameterValues['reasoning']) {
  return [
    value.toggle && '可开关',
    value.effort && value.levels.map((level) => effortLabels[level]).join('、'),
    value.budget &&
      [
        '可调预算',
        value.min && `下限 ${numberLabel(value.min)}`,
        value.max && `上限 ${numberLabel(value.max)}`,
      ]
        .filter(Boolean)
        .join(' · '),
  ]
    .filter(Boolean)
    .join(' · ')
}

export function planParameterFill(
  current: ParameterValues,
  reference: ReferenceModel,
  overwrite = false
) {
  const changes: Partial<ParameterValues> = {}
  const rows: PreviewRow[] = []
  const context = Number(current.context_window)
  const output = Number(current.max_output)
  const availableLimit = (value: number | null): value is number =>
    value != null &&
    Number.isSafeInteger(value) &&
    value >= 1 &&
    value <= 100_000_000
  const pairedUpdate =
    overwrite &&
    availableLimit(reference.context_window) &&
    availableLimit(reference.max_output) &&
    reference.max_output <= reference.context_window
  for (const [key, label, conflicts] of [
    ['context_window', '上下文上限', (value: number) => value < output],
    [
      'max_output',
      '最大输出',
      (value: number) => {
        const bound = Number(changes.context_window) || context
        return bound > 0 && value > bound
      },
    ],
  ] as const) {
    const proposed = reference[key]
    const available = availableLimit(proposed)
    const action =
      current[key] &&
      (!overwrite || !available || Number(current[key]) === proposed)
        ? '保留'
        : !available
          ? '留空'
          : !pairedUpdate && conflicts(proposed)
            ? '与已填参数冲突'
            : current[key]
              ? '覆盖'
              : '填入'
    rows.push({
      label,
      current: current[key] ? numberLabel(current[key]) : undefined,
      reference: available ? numberLabel(proposed) : undefined,
      action,
    })
    if (action === '填入' || action === '覆盖') changes[key] = String(proposed)
  }
  const declarations = { ...current.capabilities }
  const declarationLabel = (value: string) =>
    value === 'supported'
      ? '支持'
      : value === 'unsupported'
        ? '不支持'
        : undefined
  const savedReasoning = reasoningLabel(current.reasoning)
  for (const [key, label] of capabilities) {
    if (key === 'streaming') continue
    const saved = declarationLabel(declarations[key])
    const proposed = reference.capabilities[key] ?? 'unknown'
    const available = declarationLabel(proposed)
    const conflictingReasoning =
      key === 'reasoning' && proposed === 'unsupported' && !!savedReasoning
    const apply =
      available &&
      (!saved || (overwrite && proposed !== declarations[key])) &&
      !conflictingReasoning
    rows.push({
      label,
      current: saved,
      reference: available,
      action: conflictingReasoning
        ? '与已填参数冲突'
        : apply
          ? saved
            ? '覆盖'
            : '填入'
          : saved
            ? '保留'
            : '留空',
    })
    if (apply) {
      declarations[key] = proposed
      changes.capabilities = declarations
    }
  }
  const proposedReasoning = reasoningValues(reference.reasoning_options)
  const availableReasoning = reasoningLabel(proposedReasoning)
  const reasoningAction =
    savedReasoning &&
    (!overwrite || !availableReasoning || savedReasoning === availableReasoning)
      ? '保留'
      : !availableReasoning
        ? '留空'
        : declarations.reasoning !== 'supported' ||
            reference.capabilities.reasoning !== 'supported'
          ? '与已填参数冲突'
          : savedReasoning
            ? '覆盖'
            : '填入'
  rows.push({
    label: '推理选项',
    current: savedReasoning,
    reference: availableReasoning,
    action: reasoningAction,
  })
  if (reasoningAction === '填入' || reasoningAction === '覆盖')
    changes.reasoning = proposedReasoning

  return {
    rows,
    changes,
    count: rows.filter((row) => row.action === '填入' || row.action === '覆盖')
      .length,
  }
}
