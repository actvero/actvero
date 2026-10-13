import type { UseFormReturn } from 'react-hook-form'
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { MemberPicker } from '@/components/member-picker'
import { CategoryPicker } from './category-picker'
import type { Metadata } from './form-schema'
import { SkillIconField } from './icon-field'
import { scopeLabels } from './shared'

export function MetadataFields({
  form,
  disabled,
  packageIcon,
  iconWarning,
}: {
  form: UseFormReturn<Metadata>
  disabled: boolean
  packageIcon?: string
  iconWarning?: string
}) {
  const audience = form.watch('audience')
  return (
    <>
      <div className='flex items-center gap-4'>
        <FormField
          control={form.control}
          name='icon_selection'
          render={({ field }) => (
            <SkillIconField
              value={field.value}
              onChange={field.onChange}
              name={form.watch('display_name')}
              disabled={disabled}
              packageIcon={packageIcon}
              warning={iconWarning}
            />
          )}
        />
        <FormField
          control={form.control}
          name='display_name'
          render={({ field }) => (
            <FormItem className='min-w-0 flex-1'>
              <FormLabel>显示名称</FormLabel>
              <FormControl>
                <Input {...field} maxLength={100} disabled={disabled} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>
      <FormField
        control={form.control}
        name='description'
        render={({ field }) => (
          <FormItem>
            <FormLabel>简介</FormLabel>
            <FormControl>
              <Textarea
                {...field}
                rows={3}
                maxLength={1024}
                disabled={disabled}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name='category'
        render={({ field }) => (
          <FormItem>
            <FormLabel>类别</FormLabel>
            <FormControl>
              <CategoryPicker
                value={field.value ?? 'uncategorized'}
                onValueChange={field.onChange}
                onBlur={field.onBlur}
                ref={field.ref}
                disabled={disabled}
                className='w-full'
              />
            </FormControl>
            <FormDescription>
              每个技能选择一个类别，所有版本共用。
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name='audience'
        render={({ field }) => (
          <FormItem>
            <FormLabel>使用范围</FormLabel>
            <Select
              value={field.value}
              onValueChange={(v) => {
                field.onChange(v)
              }}
              disabled={disabled}
            >
              <FormControl>
                <SelectTrigger className='w-full'>
                  <SelectValue placeholder='请选择使用范围' />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {Object.entries(scopeLabels).map(([v, label]) => (
                  <SelectItem key={v} value={v}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormDescription>
              所有版本共用此范围，修改后立即生效。管理员始终可管理。
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      {audience === 'selected' && (
        <FormField
          control={form.control}
          name='member_ids'
          render={({ field }) => (
            <FormItem>
              <FormLabel>指定成员</FormLabel>
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
    </>
  )
}
