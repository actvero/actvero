import { lazy, Suspense } from 'react'
import { LoadingState } from '@/components/request-state'
import { NativeLanguage } from './native-language'

const NativeModelManagement = lazy(() =>
  import('./native-models').then((module) => ({
    default: module.NativeModelManagement,
  }))
)

export function GatewayModels() {
  return (
    <NativeLanguage>
      <Suspense fallback={<LoadingState />}>
        <NativeModelManagement />
      </Suspense>
    </NativeLanguage>
  )
}
