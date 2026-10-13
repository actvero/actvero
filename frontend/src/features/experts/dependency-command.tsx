import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { RequestError } from '@/components/request-state'
import type { useDependencyCommand } from './use-dependency-command'

export function DependencyRecoveryNotice({
  command,
}: {
  command: ReturnType<typeof useDependencyCommand>
}) {
  return (
    <>
      {command.pending && (
        <Alert>
          <AlertTitle>更新结果待确认</AlertTitle>
          <AlertDescription>
            <p>已保存原更新编号。查询或重试均沿用原内容，不创建重复更新。</p>
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={command.busy || command.forbidden}
                onClick={() => void command.recover()}
              >
                查询更新回执
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={command.busy || command.forbidden}
                onClick={() => void command.replay()}
              >
                按原编号重试
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
      {command.error != null && <RequestError error={command.error} />}
    </>
  )
}
