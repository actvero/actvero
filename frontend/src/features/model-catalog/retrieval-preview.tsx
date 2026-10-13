import { type Schema } from '@/lib/api'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'

export function RetrievalPreview({
  vectors = [],
  ranks = [],
  inputTokens,
}: {
  vectors?: Schema['VectorPreview'][]
  ranks?: Schema['RankPreview'][]
  inputTokens?: number | null
}) {
  return (
    <>
      {!!vectors.length && (
        <div role='status' className='flex min-w-0 flex-col gap-2'>
          <p>
            返回 {vectors.length} 条向量 · {vectors[0].dimensions} 维
            {inputTokens !== undefined &&
              ` · 输入用量 ${inputTokens ?? '未知'}`}
          </p>
          {vectors.map((vector) => (
            <p
              key={vector.index}
              className='text-sm break-all text-muted-foreground'
            >
              #{vector.index + 1} [{vector.values.join(', ')}
              {vector.dimensions > vector.values.length ? ', …' : ''}]
            </p>
          ))}
        </div>
      )}
      {!!ranks.length && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>排名</TableHead>
              <TableHead>原文档</TableHead>
              <TableHead>相关性</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ranks.map((item, index) => (
              <TableRow key={item.index}>
                <TableCell>{index + 1}</TableCell>
                <TableCell>#{item.index + 1}</TableCell>
                <TableCell>{item.relevance_score}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  )
}
