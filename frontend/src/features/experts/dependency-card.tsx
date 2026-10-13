import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { SearchSelect } from '@/components/search-select'
import { ServiceIcon } from '@/features/mcp/presentation'
import { useExperts, type Content } from './shared'

type Dependency = Content['skills'][number] | Content['connectors'][number]

export function DependencyCard({
  reference,
  disabled,
  onRequiredChange,
  onLoadChange,
  onToolsChange,
  onRemove,
}: {
  reference: Dependency
  disabled: boolean
  onRequiredChange: (value: boolean) => void
  onLoadChange?: (value: 'always' | 'on_demand') => void
  onToolsChange?: (value: string[]) => void
  onRemove: () => void
}) {
  const { key } = useExperts()
  const id = useId()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const skill = 'skill_id' in reference ? reference : null
  const connector = 'connector_id' in reference ? reference : null
  const kind = skill ? 'skills' : 'connectors'
  const resourceId = skill?.skill_id ?? connector?.connector_id
  const versionId = skill?.version_id
  const query = useQuery({
    queryKey: [...key, 'dependency', kind, resourceId, versionId],
    queryFn: ({ signal }) =>
      api<Schema['ExpertDependencyOption']>(
        `/experts/dependencies/${kind}/${resourceId}${versionId ? `?version_id=${versionId}` : ''}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const details = query.data
  const tools = details?.tools ?? []
  const available = tools.filter((t) => t.enabled).map((t) => t.key)
  const selected = connector?.tools ?? available
  const missing = selected.filter((name) => !tools.some((t) => t.key === name))
  const entries = [
    ...tools,
    ...missing.map((name) => ({
      key: name,
      name,
      description: '已不在当前目录中，可关闭以移除选择。',
      enabled: false,
    })),
  ]
  const filtered = entries.filter((t) =>
    `${t.name} ${t.key} ${t.description}`
      .toLocaleLowerCase()
      .includes(search.trim().toLocaleLowerCase())
  )
  const enabledCount = selected.filter((name) =>
    available.includes(name)
  ).length
  const selectionDisabled = disabled || query.isFetching || query.isError

  return (
    <Collapsible open={open} onOpenChange={setOpen} asChild>
      <Card density='compact'>
        <CardHeader layout='row' className='gap-3 py-2'>
          {skill ? (
            <ResourceIcon image={details?.icon} name={reference.label} />
          ) : (
            <ServiceIcon
              icon={details?.icon}
              name={reference.label}
              size='md'
            />
          )}
          <div className='flex min-w-0 flex-1 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <CardTitle size='body' className='break-words'>
                {details?.name ?? reference.label}
              </CardTitle>
              {skill && details?.version && (
                <Badge variant='secondary'>v{details.version}</Badge>
              )}
              {details?.update_available && (
                <Badge variant='secondary'>有新版，可保留此版本</Badge>
              )}
              {details && (
                <Badge
                  variant={
                    details.status === 'available' ? 'outline' : 'secondary'
                  }
                >
                  {details.status === 'version_conflict'
                    ? '版本待更新'
                    : details.status === 'unavailable'
                      ? skill
                        ? '版本不可用'
                        : '连接器已关闭'
                      : skill
                        ? '已锁定'
                        : '已启用'}
                </Badge>
              )}
            </div>
            {query.isPending ? (
              <Skeleton className='h-4 w-48 max-w-full' />
            ) : (
              <CardDescription className='line-clamp-2 break-words'>
                {details?.description || '暂无简介'}
              </CardDescription>
            )}
          </div>
          <Button
            type='button'
            variant='ghost'
            size='icon'
            aria-label={`移除${reference.label}`}
            disabled={disabled}
            onClick={onRemove}
          >
            <X />
          </Button>
        </CardHeader>
        <CardContent className='flex flex-col gap-3 px-4 pb-2'>
          {query.isError && (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          )}
          <div className='flex flex-wrap items-start gap-x-6 gap-y-3'>
            <div className='flex min-w-0 flex-col gap-1.5'>
              <div className='flex items-center gap-2'>
                <Label htmlFor={`${id}-required`}>使用要求</Label>
                <SearchSelect
                  id={`${id}-required`}
                  aria-label={`${reference.label}的使用要求`}
                  aria-describedby={`${id}-required-hint`}
                  disabled={disabled}
                  value={reference.required ? 'required' : 'optional'}
                  onValueChange={(v) => onRequiredChange(v === 'required')}
                  items={[
                    { value: 'required', label: '必须可用' },
                    { value: 'optional', label: '可缺省' },
                  ]}
                />
              </div>
              <p
                id={`${id}-required-hint`}
                className='text-xs text-muted-foreground'
              >
                {reference.required
                  ? '缺少时无法启动专家。'
                  : '缺少时仍可启动，跳过此项。'}
              </p>
            </div>
            {skill && (
              <div className='flex min-w-0 flex-col gap-1.5'>
                <div className='flex items-center gap-2'>
                  <Label htmlFor={`${id}-load`}>加载方式</Label>
                  <SearchSelect
                    id={`${id}-load`}
                    aria-label={`${reference.label}的加载方式`}
                    aria-describedby={`${id}-load-hint`}
                    disabled={disabled}
                    value={skill.load ?? 'always'}
                    onValueChange={(v) =>
                      onLoadChange?.(v as 'always' | 'on_demand')
                    }
                    items={[
                      { value: 'always', label: '开始时加载' },
                      { value: 'on_demand', label: '按需加载' },
                    ]}
                  />
                </div>
                <p
                  id={`${id}-load-hint`}
                  className='text-xs text-muted-foreground'
                >
                  {skill.load === 'on_demand'
                    ? '需要时再读取技能指令。'
                    : '会话开始时读取技能指令。'}
                </p>
              </div>
            )}
            {connector && (
              <CollapsibleTrigger asChild>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  className='sm:ms-auto'
                  aria-label={`${reference.label}的工具设置`}
                >
                  {details
                    ? `工具 ${enabledCount} / ${tools.length}`
                    : '工具设置'}
                  {open ? <ChevronUp /> : <ChevronDown />}
                </Button>
              </CollapsibleTrigger>
            )}
          </div>
        </CardContent>
        {connector && (
          <CollapsibleContent>
            <Separator />
            <CardContent className='flex flex-col gap-3 px-4 pt-3 pb-2'>
              <p className='text-sm text-muted-foreground'>
                仅影响当前专家，保存草稿并发布新版本后生效。平台已关闭的工具无法调用。
              </p>
              {connector.tools == null && (
                <p className='text-xs text-muted-foreground'>
                  当前跟随连接器开放的工具；调整后只使用选中的工具，后续新增工具需手动开启。
                </p>
              )}
              {query.isPending ? (
                <Skeleton className='h-16 w-full' />
              ) : query.isError ? null : !details?.tools_discovered ? (
                <p className='text-sm text-muted-foreground'>
                  尚未发现工具，请先在连接器管理中连接并刷新能力，再重新载入。
                </p>
              ) : (
                <>
                  <div className='flex flex-wrap items-center gap-2'>
                    <Input
                      className='min-w-0 flex-1 basis-40'
                      aria-label={`搜索${reference.label}的工具`}
                      placeholder='搜索工具…'
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                    <Button
                      type='button'
                      variant='ghost'
                      size='sm'
                      disabled={selectionDisabled || !available.length}
                      onClick={() => onToolsChange?.(available)}
                    >
                      全选可用
                    </Button>
                    <Button
                      type='button'
                      variant='ghost'
                      size='sm'
                      disabled={selectionDisabled || !selected.length}
                      onClick={() => onToolsChange?.([])}
                    >
                      全部关闭
                    </Button>
                  </div>
                  <div className='flex max-h-80 flex-col gap-3 overflow-y-auto'>
                    {filtered.map((tool) => (
                      <div key={tool.key} className='flex items-center gap-4'>
                        <div className='flex min-w-0 flex-1 flex-col gap-1'>
                          <div className='flex flex-wrap items-center gap-2'>
                            <Label
                              htmlFor={`${id}-${tool.key}`}
                              className='break-all'
                            >
                              {tool.name}
                            </Label>
                            {!tool.enabled && (
                              <Badge variant='secondary'>平台未开放</Badge>
                            )}
                          </div>
                          {tool.name !== tool.key && (
                            <p className='text-xs break-all text-muted-foreground'>
                              {tool.key}
                            </p>
                          )}
                          <p className='text-sm break-words text-muted-foreground'>
                            {tool.description || '暂无说明'}
                          </p>
                        </div>
                        <Switch
                          id={`${id}-${tool.key}`}
                          aria-label={`${reference.label}：${tool.name}`}
                          checked={selected.includes(tool.key)}
                          disabled={
                            selectionDisabled ||
                            (!tool.enabled && !selected.includes(tool.key))
                          }
                          onCheckedChange={(checked) =>
                            onToolsChange?.(
                              checked
                                ? [...selected, tool.key]
                                : selected.filter((name) => name !== tool.key)
                            )
                          }
                        />
                      </div>
                    ))}
                    {!filtered.length && (
                      <p className='text-sm text-muted-foreground'>
                        {entries.length ? '没有匹配的工具' : '此连接器没有工具'}
                      </p>
                    )}
                  </div>
                  {selected.length === 0 && (
                    <p className='text-xs text-muted-foreground'>
                      此专家不使用该连接器的工具；提示词与资源仍沿用连接器权限。
                    </p>
                  )}
                </>
              )}
            </CardContent>
          </CollapsibleContent>
        )}
      </Card>
    </Collapsible>
  )
}
