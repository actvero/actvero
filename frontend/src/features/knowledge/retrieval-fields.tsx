import { useId } from 'react'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Choice } from './controls'
import { retrievalLabels, type Defaults, type RetrievalPolicy } from './shared'

export function RetrievalFields({
  value,
  onChange,
  data,
  onReset,
  fixedEmbeddingId,
}: {
  value: RetrievalPolicy
  onChange: (value: RetrievalPolicy) => void
  data: Defaults
  onReset?: () => void
  fixedEmbeddingId?: string
}) {
  const id = useId()
  const vectorWeight = value.vector_weight ?? 50
  const embeddings = data.models.filter(
    (model) =>
      model.kind === 'embedding' &&
      (!fixedEmbeddingId || model.id === fixedEmbeddingId)
  )
  const rerankers = data.models.filter((model) => model.kind === 'rerank')
  const rerankEnabled = Boolean(value.rerank_model_id)
  return (
    <FieldGroup className='gap-4'>
      <Field>
        <FieldLabel>检索方式</FieldLabel>
        <Choice
          label='检索方式'
          value={value.mode ?? 'keyword'}
          items={Object.entries(retrievalLabels).map(([value, label]) => ({
            value,
            label,
          }))}
          onChange={(mode) =>
            onChange({
              ...value,
              mode: mode as RetrievalPolicy['mode'],
              embedding_model_id:
                value.embedding_model_id ??
                fixedEmbeddingId ??
                data.embedding_model_id ??
                null,
            })
          }
        />
      </Field>
      {value.mode !== 'keyword' && (
        <Field>
          <FieldLabel>向量模型</FieldLabel>
          <Choice
            label='向量模型'
            value={value.embedding_model_id ?? ''}
            items={[
              ...(value.embedding_model_id &&
              !embeddings.some((m) => m.id === value.embedding_model_id)
                ? [
                    {
                      value: value.embedding_model_id,
                      label: '当前向量模型不可用',
                    },
                  ]
                : []),
              ...embeddings.map((model) => ({
                value: model.id,
                label: `${model.name} · ${model.dimensions} 维`,
              })),
            ]}
            onChange={(model) =>
              onChange({ ...value, embedding_model_id: model })
            }
          />
          {embeddings.length === 0 && (
            <FieldError>暂无可用的向量模型</FieldError>
          )}
        </Field>
      )}
      <Field>
        <div className='flex items-center gap-3'>
          <FieldLabel htmlFor={id}>重排序</FieldLabel>
          <Switch
            id={id}
            checked={rerankEnabled}
            disabled={!rerankEnabled && rerankers.length === 0}
            onCheckedChange={(checked) => {
              onChange({
                ...value,
                rerank_model_id: checked
                  ? (rerankers.find((m) => m.id === data.rerank_model_id)?.id ??
                    rerankers[0]?.id ??
                    null)
                  : null,
              })
            }}
          />
        </div>
        {rerankEnabled && (
          <Choice
            label='重排模型'
            value={value.rerank_model_id ?? ''}
            items={[
              ...(value.rerank_model_id &&
              !rerankers.some((m) => m.id === value.rerank_model_id)
                ? [
                    {
                      value: value.rerank_model_id,
                      label: '当前重排模型不可用',
                    },
                  ]
                : []),
              ...rerankers.map((model) => ({
                value: model.id,
                label: model.name,
              })),
            ]}
            onChange={(model) => onChange({ ...value, rerank_model_id: model })}
          />
        )}
        {rerankers.length === 0 && <FieldError>暂无可用的重排模型</FieldError>}
      </Field>
      {value.mode === 'hybrid' && (
        <CollapsibleSection title='高级设置'>
          <Field className='gap-3'>
            <FieldLabel>混合权重</FieldLabel>
            <Slider
              thumbLabel='向量排名权重（百分比）'
              min={1}
              max={99}
              value={[vectorWeight]}
              onValueChange={([weight]) =>
                onChange({ ...value, vector_weight: weight })
              }
            />
            <div className='flex justify-between gap-2 text-sm text-muted-foreground'>
              <span>关键词 {100 - vectorWeight}%</span>
              <span>向量 {vectorWeight}%</span>
            </div>
          </Field>
        </CollapsibleSection>
      )}
      {onReset && (
        <Button className='self-end' variant='ghost' onClick={onReset}>
          恢复组织默认
        </Button>
      )}
    </FieldGroup>
  )
}
