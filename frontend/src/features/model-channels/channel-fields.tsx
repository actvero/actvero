import { useFormContext, useWatch } from 'react-hook-form'
import { Network } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { CollapsibleSection } from '@/components/ui/collapsible'
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
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SelectionRow } from '@/components/ui/selection-row'
import { Switch } from '@/components/ui/switch'
import { AvatarEditor } from '@/components/avatar-editor'
import { PasswordInput } from '@/components/password-input'
import type { ChannelValues } from './channel-form'
import { providerAvatarPicker } from './provider-avatars'
import { providerImage, type ProviderModule } from './provider-modules'

export function ChannelConnectionFields({
  provider,
  pending,
  needsKey,
  invalidate,
}: {
  provider: ProviderModule
  pending: boolean
  needsKey: boolean
  invalidate: () => void
}) {
  const form = useFormContext<ChannelValues>()
  const icon = useWatch({ control: form.control, name: 'icon' })
  const authMode = useWatch({ control: form.control, name: 'auth_mode' })
  return (
    <div className='flex min-w-0 flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>基本信息</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <div className='flex items-center gap-4'>
            <AvatarEditor
              value={icon || providerImage(provider) || ''}
              label='渠道图标'
              fallback={<Network />}
              disabled={pending}
              presetPicker={providerAvatarPicker}
              resetToDefault
              onChange={async (file) => {
                if (!file) {
                  form.setValue('icon', '', { shouldDirty: true })
                  return
                }
                const value = await new Promise<string>((resolve, reject) => {
                  const reader = new FileReader()
                  reader.onload = () => resolve(String(reader.result))
                  reader.onerror = () => reject(new Error('图片读取失败'))
                  reader.readAsDataURL(file)
                })
                form.setValue('icon', value, { shouldDirty: true })
              }}
            />
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem className='min-w-0 flex-1'>
                  <FormLabel>渠道名称</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      autoComplete='off'
                      placeholder='例如：团队模型服务'
                    />
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
                <FormLabel>说明</FormLabel>
                <FormControl>
                  <Input {...field} placeholder='可选' maxLength={500} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='manual_enabled'
            render={({ field }) => (
              <FormItem className='flex items-center justify-between gap-4'>
                <div>
                  <FormLabel>启用渠道</FormLabel>
                </div>
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    disabled={pending}
                  />
                </FormControl>
              </FormItem>
            )}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>连接配置</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <FormField
            control={form.control}
            name='base_url'
            render={({ field }) => (
              <FormItem>
                <FormLabel>BaseURL</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    onChange={(event) => {
                      field.onChange(event)
                      invalidate()
                    }}
                    placeholder='https://api.example.com/v1'
                    autoComplete='off'
                    spellCheck={false}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='auth_mode'
            render={({ field }) => (
              <FormItem>
                <FormLabel>身份认证</FormLabel>
                <Select
                  value={field.value}
                  onValueChange={(value) => {
                    field.onChange(value)
                    invalidate()
                    if (value === 'none') form.setValue('api_key', '')
                  }}
                  disabled={pending}
                >
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='api_key'>API Key</SelectItem>
                      {provider.allow_no_auth && (
                        <SelectItem value='none'>无认证</SelectItem>
                      )}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          {authMode === 'api_key' && (
            <FormField
              control={form.control}
              name='api_key'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API Key</FormLabel>
                  <FormControl>
                    <PasswordInput
                      {...field}
                      onChange={(event) => {
                        field.onChange(event)
                        invalidate()
                      }}
                      autoComplete='new-password'
                      placeholder={
                        needsKey ? '填写上游 API Key' : '已配置，留空保留原密钥'
                      }
                    />
                  </FormControl>
                  {!needsKey && (
                    <FormDescription>
                      留空保留原密钥；修改地址需要重新填写。
                    </FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

const operationChoices = [
  { operation: 'chat', endpoint: 'chat_completions', label: '对话补全' },
  { operation: 'embedding', endpoint: 'embeddings', label: '文本向量' },
  { operation: 'rerank', endpoint: 'rerank', label: '重排' },
  { operation: 'image_generation', endpoint: 'images', label: '单张图片生成' },
  { operation: 'speech', endpoint: 'speech', label: '语音合成测试' },
] as const

export function ChannelAdvancedFields({
  provider,
  pending,
}: {
  provider: ProviderModule
  pending: boolean
}) {
  const form = useFormContext<ChannelValues>()
  const models = useWatch({ control: form.control, name: 'models' })
  const selectedModel = useWatch({
    control: form.control,
    name: 'test_upstream_id',
  })
  const selectedOperation = useWatch({
    control: form.control,
    name: 'test_operation',
  })
  const testStream = useWatch({ control: form.control, name: 'test_stream' })
  const declaredApis = useWatch({
    control: form.control,
    name: 'declared_apis',
  })
  const choices = operationChoices.filter(
    ({ operation, endpoint }) =>
      provider.test_operations.includes(operation) &&
      (operation === 'speech' || declaredApis.includes(endpoint))
  )
  const unavailableDefault =
    !!selectedModel &&
    (!models.includes(selectedModel) ||
      !choices.some(({ operation }) => operation === selectedOperation) ||
      (testStream && selectedOperation !== 'chat'))
  return (
    <div className='flex max-w-2xl min-w-0 flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>测试默认</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <FormField
            control={form.control}
            name='test_upstream_id'
            render={({ field }) => (
              <FormItem>
                <FormLabel>上游模型</FormLabel>
                <Select
                  value={field.value || '__none'}
                  onValueChange={(value) =>
                    field.onChange(value === '__none' ? '' : value)
                  }
                  disabled={pending}
                >
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue placeholder='不设置默认模型' />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='__none'>不设置默认模型</SelectItem>
                      {selectedModel && !models.includes(selectedModel) && (
                        <SelectItem value={selectedModel}>
                          {selectedModel}（已失效）
                        </SelectItem>
                      )}
                      {models.map((id) => (
                        <SelectItem key={id} value={id}>
                          {id}
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
            name='test_operation'
            render={({ field }) => (
              <FormItem>
                <FormLabel>测试类型与接口</FormLabel>
                <Select
                  value={field.value || '__none'}
                  onValueChange={(value) => {
                    field.onChange(value === '__none' ? '' : value)
                    form.setValue('test_stream', false, { shouldDirty: true })
                  }}
                  disabled={pending || !selectedModel}
                >
                  <FormControl>
                    <SelectTrigger className='w-full'>
                      <SelectValue placeholder='请选择当前已接入的测试接口' />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value='__none'>不设置</SelectItem>
                      {selectedOperation &&
                        !choices.some(
                          ({ operation }) => operation === selectedOperation
                        ) && (
                          <SelectItem value={selectedOperation}>
                            {selectedOperation}（已失效）
                          </SelectItem>
                        )}
                      {choices.map(({ operation, label }) => (
                        <SelectItem key={operation} value={operation}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormDescription>
                  接口随所选测试类型确定；对话可逐段显示测试输出。
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          {selectedOperation === 'chat' && (
            <FormField
              control={form.control}
              name='test_stream'
              render={({ field }) => (
                <FormItem>
                  <div className='flex items-center justify-between gap-4'>
                    <FormLabel>默认流式测试</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={pending || !selectedModel}
                      />
                    </FormControl>
                  </div>
                  <FormDescription>
                    仅预填单项对话测试；批量测试仍一次返回结果。
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
          {unavailableDefault && (
            <Alert variant='destructive'>
              <AlertTitle>保存的测试默认已失效</AlertTitle>
              <AlertDescription>
                请重新选择已登记模型和可用接口，或清除默认项。
              </AlertDescription>
            </Alert>
          )}
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='self-start'
            disabled={
              pending || (!selectedModel && !selectedOperation && !testStream)
            }
            onClick={() => {
              form.setValue('test_upstream_id', '', { shouldDirty: true })
              form.setValue('test_operation', '', { shouldDirty: true })
              form.setValue('test_stream', false, { shouldDirty: true })
            }}
          >
            清除默认
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>允许接口与保护</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          {provider.member_inference ? (
            <CollapsibleSection title='允许调用的接口'>
              <FormField
                control={form.control}
                name='declared_apis'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className='sr-only'>允许调用的接口</FormLabel>
                    <FormControl>
                      <div role='group' aria-label='允许调用的接口'>
                        {(
                          [
                            ['chat_completions', '对话补全', 'chat'],
                            ['embeddings', '文本向量', 'embedding'],
                            ['rerank', '重排', 'rerank'],
                            ['images', '单张图片生成', 'image_generation'],
                          ] as const
                        )
                          .filter(([, , operation]) =>
                            provider.member_operations.includes(operation)
                          )
                          .map(([value, label]) => (
                            <SelectionRow key={value}>
                              <Checkbox
                                checked={field.value.includes(value)}
                                disabled={pending}
                                onCheckedChange={(checked) =>
                                  field.onChange(
                                    checked
                                      ? [...field.value, value]
                                      : field.value.filter(
                                          (item) => item !== value
                                        )
                                  )
                                }
                              />
                              {label}
                            </SelectionRow>
                          ))}
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CollapsibleSection>
          ) : (
            <p className='text-sm text-muted-foreground'>
              此供应商当前仅支持配置与管理员诊断。
            </p>
          )}
          {declaredApis.some(
            (item) =>
              item === 'responses' ||
              !['chat_completions', 'embeddings', 'rerank', 'images'].includes(
                item
              )
          ) && (
            <Alert>
              <AlertTitle>保留历史接口声明</AlertTitle>
              <AlertDescription>
                旧配置包含尚未接入的接口，普通编辑不会清除；当前不会因此开放成员调用。
              </AlertDescription>
            </Alert>
          )}
          <FormField
            control={form.control}
            name='automatic_protection'
            render={({ field }) => (
              <FormItem className='flex items-center justify-between gap-4'>
                <div>
                  <FormLabel>自动保护</FormLabel>
                  <FormDescription>
                    控制执行服务的一般故障冷却；关闭后认证错误和上游限流仍由执行服务处理。
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    disabled={pending}
                  />
                </FormControl>
              </FormItem>
            )}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>连接高级项</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <FormField
            control={form.control}
            name='timeout_seconds'
            render={({ field }) => (
              <FormItem>
                <FormLabel>请求超时（秒）</FormLabel>
                <FormDescription>
                  用于渠道目录检查与诊断。正式模型调用使用模型管理中的请求时限。
                </FormDescription>
                <FormControl>
                  <Input
                    {...field}
                    type='number'
                    min={3}
                    max={60}
                    onChange={(event) => {
                      field.onChange(event.target.valueAsNumber)
                    }}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>
    </div>
  )
}
