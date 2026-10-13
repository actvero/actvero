import { useEffect, useState } from 'react'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { CopyableField } from '@/components/copyable-field'
import { LoadingState, RequestError } from '@/components/request-state'

export function KeySecretDialog({
  item,
  path,
  csrf,
  onClose,
  restore,
}: {
  item: Schema['KeyView']
  path: string
  csrf: string
  onClose: () => void
  restore: () => void
}) {
  const [secret, setSecret] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void api<Schema['KeySecret']>(
      `${path}/${item.id}/reveal`,
      'POST',
      { version: item.version },
      csrf,
      controller.signal
    )
      .then((result) => {
        if (!controller.signal.aborted) setSecret(result.secret)
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error)
      })
    return () => controller.abort()
  }, [path, item.id, item.version, csrf, attempt])
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        aria-describedby={undefined}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
      >
        <DialogHeader>
          <DialogTitle>查看密钥</DialogTitle>
        </DialogHeader>
        {error ? (
          <RequestError
            error={error}
            retry={() => {
              setError(null)
              setAttempt((n) => n + 1)
            }}
          />
        ) : !secret ? (
          <LoadingState />
        ) : (
          <CopyableField
            value={secret}
            label='API Key'
            hideLabel
            copyLabel='复制密钥'
          />
        )}
        <DialogFooter>
          <Button variant='outline' onClick={onClose}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
