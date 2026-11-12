import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { ReferenceModel } from '@/features/model-catalog/reference-models'
import type { PreviewRow } from './parameter-reference'

export function ParameterReferencePreview({
  reference,
  fillRows,
  overwriteRows,
}: {
  reference: ReferenceModel
  fillRows: PreviewRow[]
  overwriteRows: PreviewRow[]
}) {
  return (
    <div className='flex min-w-0 flex-col gap-3'>
      <h3 className='font-medium'>模型参数预览</h3>
      <p className='text-sm break-words'>
        {reference.name} · {reference.provider_name}
        <span className='block text-muted-foreground'>
          {reference.model_id}
        </span>
      </p>
      <Table aria-label='模型参数预览' className='whitespace-normal'>
        <TableHeader>
          <TableRow>
            <TableHead scope='col'>字段</TableHead>
            <TableHead scope='col'>当前</TableHead>
            <TableHead scope='col'>公开资料</TableHead>
            <TableHead scope='col'>处理</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {fillRows.map((row, index) => (
            <TableRow key={row.label}>
              <TableCell>{row.label}</TableCell>
              <TableCell>
                {row.current || '—'}
                {row.current !== overwriteRows[index].current && (
                  <span className='block text-xs text-muted-foreground'>
                    已保存 {overwriteRows[index].current || '—'}
                  </span>
                )}
              </TableCell>
              <TableCell>{row.reference || '未提供'}</TableCell>
              <TableCell>
                {row.action === overwriteRows[index].action ? (
                  row.action
                ) : (
                  <>
                    <span className='block'>填入 · {row.action}</span>
                    <span className='block'>
                      覆盖 ·{' '}
                      {overwriteRows[index].action === '覆盖'
                        ? '更新'
                        : overwriteRows[index].action}
                    </span>
                  </>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
