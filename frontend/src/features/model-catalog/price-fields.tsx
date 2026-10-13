import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { cn } from '@/lib/utils'
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
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
import { Switch } from '@/components/ui/switch'
import {
  rates,
  forKind,
  metrics,
  currencies,
  shiftDecimal,
  type ModelValues,
  type PriceKey,
} from './model-form'
import { PointPricePreview } from './point-price'
import { PriceEstimate } from './price-estimate'
import { ReferencePicker } from './reference-picker'

export function PriceFields({
  disabled,
  names,
  target,
  setTarget,
}: {
  disabled: boolean
  names: Record<string, string>
  target: string
  setTarget: (value: string) => void
}) {
  const form = useFormContext<ModelValues>()
  const bindings = useWatch({ control: form.control, name: 'bindings' })
  const targets = [
    { id: 'budget_price', label: '成员预算价格' },
    ...bindings.map((b, i) => ({
      id: `bindings.${i}.price`,
      label: `${names[b.channel_id] ?? '渠道'} / ${b.upstream_id} · 采购价格`,
    })),
  ]
  const selected = targets.find((t) => t.id === target) ?? targets[0]
  return (
    <div className='flex min-w-0 flex-col gap-6'>
      <div className='flex flex-col gap-2 sm:max-w-xl'>
        <Label htmlFor='price-target'>价格对象</Label>
        <Select
          value={selected.id}
          onValueChange={setTarget}
          disabled={disabled}
        >
          <SelectTrigger id='price-target' className='w-full'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {targets.map((t) => (
                <SelectItem value={t.id} key={t.id}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <PriceEditor
        key={selected.id}
        name={selected.id as PriceKey}
        names={names}
        setTarget={setTarget}
        disabled={disabled}
      />
    </div>
  )
}

function PriceEditor({
  name,
  names,
  setTarget,
  disabled,
}: {
  name: PriceKey
  names: Record<string, string>
  setTarget: (value: string) => void
  disabled: boolean
}) {
  const form = useFormContext<ModelValues>()
  const raw = useWatch({ control: form.control, name })
  const kind = useWatch({ control: form.control, name: 'kind' })
  const value = forKind(raw, kind)
  const transcription = kind === 'transcription'
  const single = kind === 'image_generation' || transcription
  const image = kind === 'image_generation'
  const visibleRates = kind === 'chat' ? rates : rates.slice(0, 1)
  const [currencyChanged, setCurrencyChanged] = useState(false)
  return (
    <div className='flex min-w-0 flex-col gap-6'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-center gap-3'>
            <CardTitle>{kind === 'chat' ? 'Token 单价' : '调用单价'}</CardTitle>
            {kind === 'chat' && (
              <ReferencePicker
                mode='price'
                disabled={disabled}
                priceTarget={name}
                names={names}
                preserveSlug
                applied={(target) => {
                  setTarget(target)
                  setCurrencyChanged(false)
                }}
              />
            )}
          </div>
          <CardAction>
            <FormField
              control={form.control}
              name={`${name}.enabled`}
              render={({ field }) => (
                <FormItem className='flex items-center gap-3'>
                  <FormLabel>配置价格</FormLabel>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={disabled}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardAction>
        </CardHeader>
        {value.enabled && (
          <CardContent className='flex flex-col gap-5'>
            {kind !== 'chat' && kind !== 'speech' && !single && (
              <FormField
                control={form.control}
                name={`${name}.metric`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>计价方式</FormLabel>
                    <Select
                      disabled={disabled}
                      value={field.value}
                      onValueChange={(v) => {
                        if (v !== field.value)
                          form.setValue(`${name}.input`, '', {
                            shouldDirty: true,
                          })
                        field.onChange(v)
                      }}
                    >
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          {Object.entries(metrics)
                            .filter(
                              ([k]) =>
                                k !== 'images' &&
                                k !== 'seconds' &&
                                (kind === 'rerank' || k !== 'search_units')
                            )
                            .map(([k, label]) => (
                              <SelectItem key={k} value={k}>
                                按{label}
                              </SelectItem>
                            ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <div className='grid gap-4 sm:grid-cols-2'>
              <FormField
                control={form.control}
                name={`${name}.currency`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>币种</FormLabel>
                    <Select
                      value={field.value}
                      disabled={disabled}
                      onValueChange={(v) => {
                        setCurrencyChanged(!!field.value && v !== field.value)
                        field.onChange(v)
                      }}
                    >
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue placeholder='请选择币种' />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          {currencies.map((v) => (
                            <SelectItem key={v} value={v}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name={`${name}.unit`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>录入单位</FormLabel>
                    <Select
                      value={single ? '1' : field.value}
                      disabled={disabled || single}
                      onValueChange={(v) => {
                        if (v === field.value) return
                        for (const [item] of rates)
                          form.setValue(
                            `${name}.${item}`,
                            shiftDecimal(value[item], v === '1000' ? -3 : 3),
                            { shouldDirty: true }
                          )
                        field.onChange(v)
                      }}
                    >
                      <FormControl>
                        <SelectTrigger className='w-full'>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectGroup>
                          {single ? (
                            <SelectItem value='1'>
                              {transcription ? '每秒' : '每张'}
                            </SelectItem>
                          ) : (
                            <>
                              <SelectItem value='1000'>
                                每千 {metrics[value.metric]}
                              </SelectItem>
                              <SelectItem value='1000000'>
                                每百万 {metrics[value.metric]}
                              </SelectItem>
                            </>
                          )}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            {currencyChanged && (
              <p role='status' className='text-sm text-muted-foreground'>
                币种已修改，单价值未换汇，请核对后保存。
              </p>
            )}
            <div className='grid gap-4 sm:grid-cols-6'>
              {visibleRates.map(([item, label]) => (
                <FormField
                  key={item}
                  control={form.control}
                  name={`${name}.${item}`}
                  render={({ field }) => (
                    <FormItem
                      className={cn(
                        'min-w-0',
                        item === 'input' || item === 'output'
                          ? 'sm:col-span-3'
                          : 'sm:col-span-2'
                      )}
                    >
                      <FormLabel>
                        {image
                          ? '每张单价'
                          : kind !== 'chat' && value.metric === 'search_units'
                            ? '搜索单位单价'
                            : label}
                      </FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          inputMode='decimal'
                          placeholder={
                            item === 'input' || item === 'output'
                              ? '填写单价'
                              : '未配置'
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))}
            </div>
            {kind === 'chat' && (
              <p className='text-sm text-muted-foreground'>
                缓存价格选填；留空为未配置，0 表示免费。
              </p>
            )}
          </CardContent>
        )}
      </Card>
      {value.enabled && name === 'budget_price' && (
        <CollapsibleSection title='积分单价'>
          <PointPricePreview />
        </CollapsibleSection>
      )}
      {value.enabled && <PriceEstimate name={name} disabled={disabled} />}
    </div>
  )
}
