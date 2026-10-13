import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ModelCatalogPage } from '@/features/model-catalog/page'

export const Route = createFileRoute('/_authenticated/models')({
  component: () => (
    <AccessGate admin>
      <ModelCatalogPage />
    </AccessGate>
  ),
})
