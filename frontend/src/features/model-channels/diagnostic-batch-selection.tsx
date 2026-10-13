import { useState } from 'react'
import { useIsMobile } from '@/hooks/use-mobile'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { BatchParameters } from './diagnostic-batch-parameters'
import {
  batchInputSummary,
  emptyBatchValues,
  validBatchValues,
  type BatchValues,
} from './diagnostic-batch-values'
import type { Detail } from './shared'
import { operationLabels, type TestOperation } from './test-operations'

export type SelectedBatchItem = {
  key: string
  values: BatchValues
  configured: boolean
}
const batchKey = (id: string, operation: TestOperation) =>
  `${id}\u0000${operation}`
const batchOperations: TestOperation[] = ['chat', 'embedding', 'rerank']

export function BatchSelection({
  channel,
  operations,
  selected,
  onConfirm,
  onCancel,
}: {
  channel: Detail
  operations: TestOperation[]
  selected: SelectedBatchItem[]
  onConfirm: (items: SelectedBatchItem[]) => void
  onCancel: () => void
}) {
  const mobile = useIsMobile()
  const allowed = batchOperations.filter((value) => operations.includes(value))
  const [draft, setDraft] = useState<SelectedBatchItem[]>(() =>
    selected.map((item) => ({ ...item, values: { ...item.values } }))
  )
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<TestOperation | 'all'>('all')
  const [editing, setEditing] = useState('')
  const [templateOperation, setTemplateOperation] = useState<TestOperation>(
    allowed[0] ?? 'chat'
  )
  const [templates, setTemplates] = useState<
    Partial<Record<TestOperation, BatchValues>>
  >({})
  const [templateEditing, setTemplateEditing] = useState(false)
  const candidates = channel.models
    .flatMap((model) =>
      allowed
        .filter((operation) => filter === 'all' || filter === operation)
        .map((operation) => ({
          id: model.id,
          operation,
          key: batchKey(model.id, operation),
        }))
    )
    .filter((item) =>
      item.id.toLowerCase().includes(search.trim().toLowerCase())
    )
  const visible = candidates.slice(0, 100)
  const invalid = draft.filter(
    (item) => !item.configured || !validBatchValues(item.values)
  )
  function toggle(id: string, operation: TestOperation) {
    const key = batchKey(id, operation)
    if (draft.some((item) => item.key === key)) {
      setDraft((items) => items.filter((item) => item.key !== key))
      if (editing === key) setEditing('')
      return
    }
    if (draft.length >= 50) return
    setDraft((items) => [
      ...items,
      { key, values: emptyBatchValues(id, operation), configured: false },
    ])
    setEditing(key)
  }
  const body = (
    <div className='flex min-w-0 flex-col gap-4'>
      <p className='text-sm text-muted-foreground'>
        只从已登记库存中明确选择模型与操作。供应商提供该操作不证明每个上游模型都支持；请核对模型能力。最多
        50 项；图片、语音和绑定健康认证须逐项进行，流式诊断尚未交付。
      </p>
      <div className='grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]'>
        <Input
          aria-label='搜索已登记模型'
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder='搜索已登记模型'
        />
        <Select
          value={filter}
          onValueChange={(value) => setFilter(value as TestOperation | 'all')}
        >
          <SelectTrigger className='w-full' aria-label='筛选操作'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>全部操作</SelectItem>
            {allowed.map((operation) => (
              <SelectItem key={operation} value={operation}>
                {operationLabels[operation]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div
        className='max-h-44 overflow-y-auto rounded-md border p-2'
        aria-label='可选组合'
      >
        {visible.length ? (
          visible.map(({ id, operation, key }) => {
            const checked = draft.some((item) => item.key === key)
            return (
              <label
                key={key}
                className='flex min-w-0 items-center gap-2 p-2 text-sm'
              >
                <Checkbox
                  checked={checked}
                  disabled={!checked && draft.length >= 50}
                  onCheckedChange={() => toggle(id, operation)}
                  aria-label={`选择 ${id} ${operationLabels[operation]}`}
                />
                <span className='min-w-0 break-all'>
                  {id} · {operationLabels[operation]}
                </span>
              </label>
            )
          })
        ) : (
          <p className='p-2 text-sm text-muted-foreground'>
            没有匹配的已登记组合。
          </p>
        )}
      </div>
      {candidates.length > visible.length && (
        <p className='text-sm text-muted-foreground'>
          只显示前 100 个匹配组合，请继续搜索缩小范围。
        </p>
      )}
      <p className='text-sm'>
        本次选择 {draft.length}/50
        {invalid.length ? ` · ${invalid.length} 项参数待配置或无效` : ''}
      </p>
      <div className='flex min-w-0 flex-col gap-2 rounded-md border p-3'>
        <strong className='text-sm'>同操作输入模板</strong>
        <p className='text-sm text-muted-foreground'>
          模板仅保留在本次选择中；必须先填写有效参数，应用后仍可逐项覆盖。
        </p>
        <Select
          value={templateOperation}
          onValueChange={(value) => {
            setTemplateOperation(value as TestOperation)
            setTemplateEditing(false)
          }}
        >
          <SelectTrigger className='w-full' aria-label='模板操作'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {allowed.map((operation) => (
              <SelectItem key={operation} value={operation}>
                {operationLabels[operation]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {templateEditing ? (
          <BatchParameters
            key={`template-${templateOperation}`}
            values={
              templates[templateOperation] ??
              emptyBatchValues('template', templateOperation)
            }
            label={`${operationLabels[templateOperation]}模板`}
            onSave={(values) => {
              setTemplates((old) => ({ ...old, [templateOperation]: values }))
              setTemplateEditing(false)
            }}
            onCancel={() => setTemplateEditing(false)}
          />
        ) : (
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => {
                setEditing('')
                setTemplateEditing(true)
              }}
            >
              编辑模板
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={
                !templates[templateOperation] ||
                !draft.some(
                  (item) => item.values.operation === templateOperation
                )
              }
              onClick={() => {
                const template = templates[templateOperation]
                if (!template || !validBatchValues(template)) return
                setDraft((items) =>
                  items.map((item) =>
                    item.values.operation === templateOperation
                      ? {
                          ...item,
                          values: { ...template, id: item.values.id },
                          configured: true,
                        }
                      : item
                  )
                )
              }}
            >
              应用到所选{operationLabels[templateOperation]}项
            </Button>
          </div>
        )}
      </div>
      <div className='flex min-w-0 flex-col gap-2' aria-label='逐项参数预览'>
        {draft.map((item) => (
          <div
            key={item.key}
            className='flex min-w-0 flex-col gap-2 rounded-md border p-3 text-sm'
          >
            <div className='flex min-w-0 flex-wrap items-center justify-between gap-2'>
              <strong className='min-w-0 break-all'>
                {item.values.id} ·{' '}
                {operationLabels[item.values.operation as TestOperation]}
              </strong>
              <div className='flex gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    setTemplateEditing(false)
                    setEditing(editing === item.key ? '' : item.key)
                  }}
                >
                  {editing === item.key ? '收起参数' : '查看／编辑参数'}
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() =>
                    toggle(
                      item.values.id,
                      item.values.operation as TestOperation
                    )
                  }
                >
                  移除
                </Button>
              </div>
            </div>
            <p className='text-muted-foreground'>
              {item.configured && validBatchValues(item.values)
                ? batchInputSummary(item.values)
                : '参数未配置或无效'}
            </p>
            {editing === item.key && (
              <BatchParameters
                key={item.key}
                values={item.values}
                label={`${item.values.id} 本项参数`}
                onSave={(values) => {
                  setDraft((items) =>
                    items.map((current) =>
                      current.key === item.key
                        ? { ...current, values, configured: true }
                        : current
                    )
                  )
                  setEditing('')
                }}
                onCancel={() => setEditing('')}
              />
            )}
          </div>
        ))}
      </div>
      <div className='flex flex-wrap justify-end gap-2'>
        {(editing || templateEditing) && (
          <p className='w-full text-sm text-muted-foreground'>
            请先保存或取消正在编辑的参数，再确认本次选择。
          </p>
        )}
        <Button type='button' variant='outline' onClick={onCancel}>
          取消选择
        </Button>
        <Button
          type='button'
          disabled={!!invalid.length || !!editing || templateEditing}
          onClick={() => onConfirm(draft)}
        >
          确认 {draft.length} 项
        </Button>
      </div>
    </div>
  )
  return mobile ? (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
    >
      <SheetContent className='w-full max-w-none overflow-y-auto p-4 sm:max-w-none'>
        <SheetHeader className='p-0'>
          <SheetTitle>选择批量诊断项</SheetTitle>
          <SheetDescription>本次临时选择和参数</SheetDescription>
        </SheetHeader>
        {body}
      </SheetContent>
    </Sheet>
  ) : (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
    >
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-3xl'>
        <DialogHeader>
          <DialogTitle>选择批量诊断项</DialogTitle>
          <DialogDescription>本次临时选择和参数</DialogDescription>
        </DialogHeader>
        {body}
      </DialogContent>
    </Dialog>
  )
}
