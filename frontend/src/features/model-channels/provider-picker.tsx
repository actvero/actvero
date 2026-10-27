import { useState } from 'react'
import { Network } from 'lucide-react'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SheetFooter } from '@/components/ui/sheet'
import { FilterSelect } from '@/components/filter-select'
import { providerImage, type ProviderModule } from './provider-modules'

export function ProviderPicker({
  providers,
  select,
  close,
}: {
  providers: ProviderModule[]
  select: (provider: ProviderModule) => void
  close: () => void
}) {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const filtered = providers.filter(
    (provider) =>
      provider.available_for_new_channels !== false &&
      (!category || provider.category === category) &&
      [provider.name, provider.id, ...provider.aliases]
        .join(' ')
        .toLowerCase()
        .includes(search.trim().toLowerCase())
  )
  return (
    <>
      <div className='flex min-h-0 flex-1 flex-col gap-5 p-4 sm:p-6'>
        <div className='flex flex-wrap gap-3'>
          <Input
            autoFocus
            className='min-w-0 flex-1'
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label='搜索供应商'
            placeholder='搜索供应商'
          />
          <FilterSelect
            label='供应商分类'
            value={category}
            onChange={setCategory}
            options={[
              { value: 'vendor', label: '模型厂商' },
              { value: 'aggregator', label: '聚合服务' },
              { value: 'compatible', label: '自建与兼容' },
            ]}
          />
        </div>
        <div className='min-h-0 flex-1 overflow-y-auto'>
          <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3'>
            {filtered.map((provider) => (
              <Button
                key={provider.id}
                variant='outline'
                className='h-24 w-full min-w-0 justify-start gap-3 px-5'
                aria-label={provider.name}
                onClick={() => select(provider)}
              >
                <Avatar>
                  <AvatarImage src={providerImage(provider)} alt='' />
                  <AvatarFallback>
                    <Network className='size-4' />
                  </AvatarFallback>
                </Avatar>
                <span className='flex min-w-0 flex-col items-start gap-1'>
                  <span className='max-w-full truncate'>{provider.name}</span>
                  <span className='text-xs font-normal text-muted-foreground'>
                    {provider.model_discovery
                      ? '支持从上游获取模型'
                      : '填写自己的模型 ID'}
                  </span>
                </span>
              </Button>
            ))}
          </div>
          {!filtered.length && (
            <div className='flex flex-col items-center gap-3 py-12'>
              <p className='text-sm text-muted-foreground'>没有匹配的供应商</p>
              <Button
                variant='outline'
                onClick={() => {
                  setSearch('')
                  setCategory('')
                }}
              >
                清除筛选
              </Button>
              {providers.find(
                (provider) => provider.id === 'openai-compatible'
              ) && (
                <Button
                  variant='link'
                  onClick={() =>
                    select(
                      providers.find(
                        (provider) => provider.id === 'openai-compatible'
                      )!
                    )
                  }
                >
                  使用自定义兼容服务
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
      <SheetFooter>
        <Button variant='outline' onClick={close}>
          取消
        </Button>
      </SheetFooter>
    </>
  )
}
