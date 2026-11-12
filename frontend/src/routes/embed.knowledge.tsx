import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { EmbeddedReader } from '@/features/knowledge/embed'

export const Route = createFileRoute('/embed/knowledge')({
  validateSearch: z.object({ parent_origin: z.string().max(300).catch('') })
    .parse,
  component: function ReaderRoute() {
    const search = Route.useSearch()
    return <EmbeddedReader parentOrigin={search.parent_origin} />
  },
})
