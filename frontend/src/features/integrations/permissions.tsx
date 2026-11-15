import { useId, useState } from 'react'
import { toast } from 'sonner'
import { messageOf, type Schema } from '@/lib/api'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  applicationPermissions,
  applicationSettings,
  type Application,
} from './data'

const modes = [
  { field: 'read', label: '读' },
  { field: 'write', label: '写' },
] as const

type Permission = (typeof applicationPermissions)[number]

export function ApplicationPermissions({
  app,
  save,
}: {
  app: Application
  save: (input: Schema['ApplicationUpdate']) => Promise<void>
}) {
  const root = useId()
  const [busy, setBusy] = useState(false)

  async function change(field: Permission['read' | 'write'], enabled: boolean) {
    setBusy(true)
    try {
      await save({ ...applicationSettings(app), [field]: enabled })
      toast.success('权限已更新')
    } catch (error) {
      toast.error(messageOf(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className='max-w-3xl overflow-hidden rounded-xl border'>
      <Table aria-label='应用资源权限'>
        <TableHeader className='bg-muted/50'>
          <TableRow>
            <TableHead scope='col' className='px-4'>
              资源
            </TableHead>
            {modes.map(({ field, label }) => (
              <TableHead
                key={field}
                scope='col'
                className='w-16 text-center sm:w-24'
              >
                {label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {applicationPermissions.map((permission) => {
            const { name, description, read } = permission
            const descriptionId = root + read
            return (
              <TableRow key={read}>
                <TableCell className='px-4 py-3 whitespace-normal'>
                  <div className='font-medium'>{name}</div>
                  <p id={descriptionId} className='mt-1 text-muted-foreground'>
                    {description}
                  </p>
                </TableCell>
                {modes.map(({ field, label }) => {
                  const key = permission[field]
                  return (
                    <TableCell key={key} className='text-center'>
                      <Switch
                        className='align-middle'
                        aria-label={name + label + '权限'}
                        aria-describedby={descriptionId}
                        checked={app[key]}
                        disabled={busy}
                        onCheckedChange={(checked) => void change(key, checked)}
                      />
                    </TableCell>
                  )
                })}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
