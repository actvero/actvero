import { useFormContext, useWatch } from 'react-hook-form'
import { avatarDataUrl } from '@/lib/avatar-image'
import {
  Card,
  CardAction,
  CardHeader,
  CardTitle,
  CardContent,
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { AvatarEditor } from '@/components/avatar-editor'
import { providerAvatarPicker } from '@/features/model-channels/provider-avatars'
import { ChatPolicyFields } from './chat-policy-fields'
import { ImageFields } from './image-fields'
import { MetadataSuggestion } from './metadata-suggestion'
import {
  capabilities,
  kinds,
  type ModelValues,
  type OperationKind,
} from './model-form'
import { ReasoningFields } from './reasoning-fields'
import { modelIcon } from './reference-models'
import { ReferencePicker } from './reference-picker'
import { RetrievalFields } from './retrieval-fields'
import { SpeechFields } from './speech-fields'
import { TranscriptionFields } from './transcription-fields'

export function ModelFields({
  disabled,
  showOperation = true,
  operationConfigured = true,
  existing = false,
  names = {},
  changeKind,
  showMetadataSuggestion = true,
}: {
  disabled: boolean
  showOperation?: boolean
  operationConfigured?: boolean
  existing?: boolean
  names?: Record<string, string>
  changeKind?: (kind: OperationKind) => void
  showMetadataSuggestion?: boolean
}) {
  const form = useFormContext<ModelValues>()
  const draft = useWatch({ control: form.control })
  return (
    <div className='flex min-w-0 flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>基本资料</CardTitle>
          {draft.kind === 'chat' && (
            <CardAction>
              <ReferencePicker
                mode='metadata'
                disabled={disabled}
                names={names}
                preserveSlug={existing}
              />
            </CardAction>
          )}
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <div className='flex min-w-0 flex-col gap-4 sm:flex-row sm:items-end'>
            <AvatarEditor
              value={modelIcon(draft)}
              fallback={draft.name?.slice(0, 1) || 'M'}
              label='模型图标'
              disabled={disabled}
              presetPicker={{
                ...providerAvatarPicker,
                title: '选择模型图标',
                description: '选择图标，保存模型后生效。',
              }}
              onChange={async (file) => {
                form.setValue('icon', file ? await avatarDataUrl(file) : '', {
                  shouldDirty: true,
                })
                form.setValue('icon_key', '', { shouldDirty: true })
              }}
            />
            <div className='grid min-w-0 flex-1 gap-4 sm:grid-cols-2'>
              <FormField
                control={form.control}
                name='name'
                render={({ field }) => (
                  <FormItem className='min-w-0 flex-1'>
                    <FormLabel>展示名称</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder='例如：团队通用模型' />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='slug'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>技术名称</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder='例如：team-chat' />
                    </FormControl>
                    <p className='text-xs text-muted-foreground'>
                      客户端调用时使用的模型 ID，可与上游名称不同。
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </div>
          {changeKind && (
            <FormField
              control={form.control}
              name='kind'
              render={({ field }) => (
                <FormItem className='max-w-xs'>
                  <FormLabel>模型类型</FormLabel>
                  <Select
                    value={field.value}
                    disabled={disabled}
                    onValueChange={(kind) => changeKind(kind as OperationKind)}
                  >
                    <FormControl>
                      <SelectTrigger className='w-full'>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectGroup>
                        {Object.entries(kinds).map(([kind, label]) => (
                          <SelectItem key={kind} value={kind}>
                            {label}
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
          <CollapsibleSection title='补充资料与显示排序（可选）'>
            <div className='grid gap-4 sm:grid-cols-2'>
              <FormField
                control={form.control}
                name='vendor'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>开发方（可选）</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder='未填写' />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='description'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>说明（可选）</FormLabel>
                    <FormControl>
                      <Textarea {...field} placeholder='补充模型资料' />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name='display_order'
              render={({ field }) => (
                <FormItem className='max-w-xs'>
                  <FormLabel>显示排序</FormLabel>
                  <FormControl>
                    <Input {...field} inputMode='numeric' />
                  </FormControl>
                  <p className='text-sm text-muted-foreground'>
                    数值越大，在客户端目录越靠前；不影响渠道调度。
                  </p>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CollapsibleSection>
        </CardContent>
      </Card>
      {showOperation &&
        (draft.kind === 'speech' ? (
          <SpeechFields disabled={disabled} />
        ) : draft.kind === 'transcription' ? (
          <TranscriptionFields disabled={disabled} />
        ) : draft.kind === 'image_generation' ? (
          <ImageFields disabled={disabled} />
        ) : draft.kind !== 'chat' ? (
          <RetrievalFields disabled={disabled} />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>
                {operationConfigured ? '能力与限制' : '能力资料（不创建接口）'}
              </CardTitle>
            </CardHeader>
            <CardContent className='flex flex-col gap-5'>
              {showMetadataSuggestion ? (
                <MetadataSuggestion />
              ) : (
                draft.reference && (
                  <p className='text-xs break-all text-muted-foreground'>
                    参数来源：models.dev · {draft.reference.provider} /{' '}
                    {draft.reference.model_id}
                  </p>
                )
              )}
              <div className='grid gap-4 sm:grid-cols-2'>
                {(
                  [
                    ['context_window', '上下文上限'],
                    ['max_output', '最大输出'],
                  ] as const
                ).map(([name, label]) => (
                  <FormField
                    key={name}
                    control={form.control}
                    name={name}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{label}（Token）</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            inputMode='numeric'
                            placeholder='未配置'
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
              </div>
              <div className='grid gap-4 sm:grid-cols-2'>
                {capabilities.map(([key, label]) => (
                  <FormField
                    key={key}
                    control={form.control}
                    name={`capabilities.${key}`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{label}</FormLabel>
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
                              <SelectItem value='unknown'>未知</SelectItem>
                              <SelectItem value='supported'>支持</SelectItem>
                              <SelectItem value='unsupported'>
                                不支持
                              </SelectItem>
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
              </div>
              {operationConfigured && <ReasoningFields disabled={disabled} />}
              {operationConfigured && <ChatPolicyFields disabled={disabled} />}
            </CardContent>
          </Card>
        ))}
    </div>
  )
}
