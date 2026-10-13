import { useFormContext, useWatch } from 'react-hook-form'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import {
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { MemberPicker } from '@/components/member-picker'
import type { ModelValues } from './model-form'

export function RetrievalFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<ModelValues>()
  const kind = useWatch({ control: form.control, name: 'kind' })
  const fields = [
    ...(kind === 'embedding'
      ? ([
          ['dimensions', '默认维度'],
          ['dimension_options', '可选维度（逗号分隔）'],
          ['embedding_space', '向量空间标识'],
        ] as const)
      : []),
    ...(kind === 'rerank'
      ? ([
          ['max_search_units', '搜索单位预占上限（按搜索单位计价时）'],
        ] as const)
      : []),
    ['max_batch_size', kind === 'embedding' ? '批量上限' : '最大文档数'],
    [
      'max_input_characters',
      kind === 'embedding' ? '单条字符上限' : '查询／单篇字符上限',
    ],
  ] as const
  return (
    <Card>
      <CardHeader>
        <CardTitle>能力与限制</CardTitle>
      </CardHeader>
      <CardContent className='grid gap-4 sm:grid-cols-2'>
        {fields.map(([key, label]) => (
          <FormField
            key={key}
            control={form.control}
            name={`retrieval.${key}`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>{label}</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    disabled={disabled}
                    placeholder={
                      key === 'embedding_space'
                        ? '模型版本与向量空间，如 bge-m3-v1'
                        : '未配置'
                    }
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
        {kind === 'embedding' && (
          <p className='text-sm text-muted-foreground sm:col-span-2'>
            可选维度留空时不接受 dimensions 参数。不同向量空间使用不同技术名称。
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function AccessFields({
  disabled,
  names: _names,
  singleOperation: _singleOperation = false,
}: {
  disabled: boolean
  names: Record<string, string>
  singleOperation?: boolean
}) {
  const form = useFormContext<ModelValues>()
  const policy = useWatch({ control: form.control, name: 'access' })
  return (
    <Card>
      <CardHeader>
        <CardTitle>调用设置</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        <FormField
          control={form.control}
          name='access.enabled'
          render={({ field }) => (
            <FormItem className='flex items-center justify-between'>
              <FormLabel>启用模型</FormLabel>
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
        <FormField
          control={form.control}
          name='access.audience'
          render={({ field }) => (
            <FormItem>
              <FormLabel>使用范围</FormLabel>
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={disabled}
              >
                <FormControl>
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value='administrators'>仅管理员</SelectItem>
                    <SelectItem value='selected'>指定成员</SelectItem>
                    <SelectItem value='organization'>组织全员</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        {policy.audience === 'selected' && (
          <FormField
            control={form.control}
            name='access.member_ids'
            render={({ field }) => (
              <FormItem>
                <FormLabel>可用成员</FormLabel>
                <FormControl>
                  <MemberPicker
                    value={field.value}
                    onChange={field.onChange}
                    disabled={disabled}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
        <p className='text-sm text-muted-foreground'>
          调用会产生上游费用。平台记录用量和费用试算，客户端调用按成员策略检查积分额度。
        </p>
      </CardContent>
    </Card>
  )
}
