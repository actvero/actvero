import { useState } from 'react'
import type { Schema } from '@/lib/api'
import { ChannelModelCreate } from './channel-model-create'
import { ModelEditor } from './model-editor'
import { values, type Model, type ModelValues } from './model-form'
import { ReferenceCreate } from './reference-create'
import { importModel } from './reference-models'

export function ModelCreate(props: {
  close: () => void
  saved: (model: Model) => void
  restoreFocus?: () => void
  initialChannel?: Schema['ChannelDetail']
  initialUpstream?: string
}) {
  const [draft, setDraft] = useState<ModelValues | 'manual' | null>(null)
  // A channel can offer a shortcut; the model catalogue never requires one.
  if (props.initialChannel) return <ChannelModelCreate {...props} />
  if (draft)
    return (
      <ModelEditor
        initialValues={draft === 'manual' ? undefined : draft}
        independentCreation
        close={props.close}
        saved={props.saved}
        restoreFocus={props.restoreFocus}
      />
    )
  return (
    <ReferenceCreate
      close={props.close}
      restoreFocus={props.restoreFocus}
      manual={() => setDraft('manual')}
      select={(model) => {
        const next = importModel(values(), model, false)
        next.quote_snapshots = model.quote_snapshot
          ? [model.quote_snapshot]
          : []
        setDraft(next)
      }}
    />
  )
}
