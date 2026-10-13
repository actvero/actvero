import { useState } from 'react'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SearchSelect } from '@/components/search-select'
import {
  emptyReferenceFilters,
  type ReferenceFilters,
} from './reference-filter-values'

export function ReferenceSelect({
  label,
  value,
  items,
  change,
}: {
  label: string
  value: string
  items: [string, string][]
  change: (value: string) => void
}) {
  return (
    <Select
      value={value || 'all'}
      onValueChange={(v) => change(v === 'all' ? '' : v)}
    >
      <SelectTrigger aria-label={label} className='w-full'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map(([id, name]) => (
            <SelectItem key={id} value={id}>
              {name}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

export function ReferenceFilterBar({
  search,
  setSearch,
  filters,
  change,
  facets,
  preferred,
  prioritize,
  setPrioritize,
}: {
  search: string
  setSearch: (value: string) => void
  filters: ReferenceFilters
  change: (value: ReferenceFilters) => void
  facets?: Schema['ReferenceFacets']
  preferred: string
  prioritize: boolean
  setPrioritize: (value: boolean) => void
}) {
  const [advanced, setAdvanced] = useState(false)
  const update = (key: keyof ReferenceFilters, value: string) =>
    change({ ...filters, [key]: value })
  const tri: [string, string][] = [
    ['all', '不限'],
    ['supported', '支持'],
    ['unsupported', '不支持'],
    ['unknown', '未知'],
  ]
  const modalities: [string, string][] = [
    ['all', '不限'],
    ['text', '文字'],
    ['image', '图片'],
    ['audio', '音频'],
    ['video', '视频'],
    ['pdf', 'PDF'],
  ]
  return (
    <div className='flex flex-col gap-3'>
      <Label htmlFor='reference-search' className='sr-only'>
        搜索公开模型
      </Label>
      <Input
        id='reference-search'
        placeholder='搜索模型名称、ID 或供应商'
        value={search}
        maxLength={100}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div className='grid grid-cols-2 gap-2 lg:grid-cols-[1fr_1fr_1fr_auto]'>
        <SearchSelect
          aria-label='模型开发方'
          value={filters.developer || 'all'}
          onValueChange={(v) => update('developer', v === 'all' ? '' : v)}
          items={[
            { value: 'all', label: '全部开发方' },
            ...(facets?.developers ?? []).map((p) => ({
              value: p.id,
              label: p.name,
            })),
          ]}
          searchPlaceholder='搜索开发方'
        />
        <SearchSelect
          aria-label='API 供应商'
          value={filters.provider || 'all'}
          onValueChange={(v) => update('provider', v === 'all' ? '' : v)}
          items={[
            { value: 'all', label: '全部 API 供应商' },
            ...(facets?.providers ?? []).map((p) => ({
              value: p.id,
              label: p.name,
            })),
          ]}
          searchPlaceholder='搜索 API 供应商'
        />
        <ReferenceSelect
          label='排序方式'
          value={filters.sort}
          change={(v) => update('sort', v)}
          items={[
            ['relevance', '相关度优先'],
            ['name', '名称排序'],
            ['context', '上下文从大到小'],
            ['input_price', '输入价格从低到高'],
            ['output_price', '输出价格从低到高'],
            ['released', '发布时间从新到旧'],
          ]}
        />
        <Button
          type='button'
          variant='outline'
          aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}
        >
          更多筛选
        </Button>
      </div>
      <div className='flex flex-wrap items-center gap-x-5 gap-y-2'>
        <Label className='flex items-center gap-2'>
          <Checkbox
            checked={prioritize}
            disabled={!preferred}
            onCheckedChange={(v) => setPrioritize(v === true)}
          />
          当前渠道优先
        </Label>
        <Label className='flex items-center gap-2'>
          <Checkbox
            checked={filters.price !== 'all' && filters.price !== ''}
            onCheckedChange={(v) => update('price', v ? 'available' : 'all')}
          />
          仅看有报价
        </Label>
        <Button
          type='button'
          variant='ghost'
          size='sm'
          onClick={() => {
            setSearch('')
            change({ ...emptyReferenceFilters })
            setPrioritize(true)
          }}
        >
          重置
        </Button>
      </div>
      {advanced && (
        <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
          {(
            [
              ['tools', '工具调用'],
              ['structured_output', '结构化输出'],
              ['reasoning', '思考模式'],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className='flex flex-col gap-2'>
              <Label>{label}</Label>
              <ReferenceSelect
                label={label}
                value={filters[key]}
                change={(v) => update(key, v)}
                items={tri}
              />
            </div>
          ))}
          <div className='flex flex-col gap-2'>
            <Label>最低上下文</Label>
            <ReferenceSelect
              label='最低上下文'
              value={filters.min_context}
              change={(v) => update('min_context', v)}
              items={[
                ['all', '不限'],
                ['32000', '32K'],
                ['128000', '128K'],
                ['200000', '200K'],
                ['1000000', '1M'],
              ]}
            />
          </div>
          {(
            [
              ['input_modality', '输入类型'],
              ['output_modality', '输出类型'],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className='flex flex-col gap-2'>
              <Label>{label}</Label>
              <ReferenceSelect
                label={label}
                value={filters[key]}
                change={(v) => update(key, v)}
                items={modalities}
              />
            </div>
          ))}
          <div className='flex flex-col gap-2'>
            <Label>报价条件</Label>
            <ReferenceSelect
              label='报价条件'
              value={filters.price}
              change={(v) => update('price', v || 'all')}
              items={[
                ['all', '不限'],
                ['available', '有参考报价'],
                ['importable', '可直接导入的固定单价'],
              ]}
            />
          </div>
          <div className='flex flex-col gap-2'>
            <Label>模型状态</Label>
            <ReferenceSelect
              label='模型状态'
              value={filters.status}
              change={(v) => update('status', v || 'all')}
              items={[
                ['all', '全部状态'],
                ['exclude_deprecated', '排除已弃用'],
                ['alpha', 'Alpha'],
                ['beta', 'Beta'],
                ['deprecated', '已弃用'],
              ]}
            />
          </div>
        </div>
      )}
    </div>
  )
}
