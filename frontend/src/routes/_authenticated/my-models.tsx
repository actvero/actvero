import { createFileRoute } from '@tanstack/react-router'
import { MyModelsPage } from '@/features/my-models/page'
import { readMyModelSearch } from '@/features/my-models/search'

export const Route = createFileRoute('/_authenticated/my-models')({
  validateSearch: readMyModelSearch,
  component: function Page() {
    return <MyModelsPage search={Route.useSearch()} />
  },
})
