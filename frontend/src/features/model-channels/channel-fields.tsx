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

type AddressMode = Exclude<ChannelValues['address_mode'], 'legacy_api_base'>

export function ChannelConnectionFields({
  provider,
  pending,
  needsKey,
  invalidate,
  preview,
  previewPending,
  showAdvanced,
}: {
  provider: ProviderModule
  pending: boolean
  needsKey: boolean
  invalidate: () => void
  preview: () => void
  previewPending: boolean
  showAdvanced: () => void
}) {
  const form = useFormContext<ChannelValues>()
  const icon = useWatch({ control: form.control, name: 'icon' })
  const authMode = useWatch({ control: form.control, name: 'auth_mode' })
  const addressMode = useWatch({ control: form.control, name: 'address_mode' })
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
                  <FormDescription>
                    没有已开放模型绑定时仍不可调用。
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
          <CardTitle>连接配置</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-5'>
          <FormField
            control={form.control}
            name='address_mode'
            render={({ field }) => (
              <FormItem>
                <FormLabel>地址方式</FormLabel>
                <Select
                  // Saved compatibility addresses remain internal; opening or
                  // saving the form must not change their resolved targets.
                  value={
                    field.value === 'legacy_api_base'
                      ? 'service_root'
                      : field.value
                  }
                  onValueChange={(value: AddressMode) => {
                    if (
                      field.value === 'legacy_api_base' &&
                      value === 'service_root'
                    )
                      return
                    field.onChange(value)
                    invalidate()
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
                      {provider.id !== 'openai-compatible' && (
                        <SelectItem value='provider_default'>
                          官方地址
                        </SelectItem>
                      )}
                      <SelectItem value='service_root'>自定义地址</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          {addressMode === 'provider_default' ? (
            <div className='flex min-w-0 flex-col gap-2 text-sm'>
              <p className='text-muted-foreground'>
                使用 {provider.name} 的官方地址，无需手动填写。
              </p>
              <dl className='grid min-w-0 grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-1'>
                <dt className='text-muted-foreground'>服务根</dt>
                <dd className='min-w-0 font-mono break-all'>
                  {provider.official_service_root}
                </dd>
                <dt className='text-muted-foreground'>默认接口前缀</dt>
                <dd className='min-w-0 font-mono break-all'>
                  {provider.default_api_prefix || '根路径'}
                </dd>
              </dl>
            </div>
          ) : (
            <FormField
              control={form.control}
              name={
                addressMode === 'service_root' ? 'service_root' : 'base_url'
              }
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API 基础 URL</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      onChange={(event) => {
                        field.onChange(event)
                        invalidate()
                      }}
                      placeholder='https://api.example.com'
                      autoComplete='off'
                    />
                  </FormControl>
                  <FormDescription>
                    {addressMode === 'service_root'
                      ? '填写第三方代理或自建服务的地址，请勿添加 /v1 或尾部斜杠。特殊接口前缀可在高级设置中配置。'
                      : '填写供应商提供的 API 基础 URL，可通过下方预览查看最终请求地址。'}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
          {provider.setup_help && (
            <Alert>
              <AlertTitle>接入说明</AlertTitle>
              <AlertDescription>{provider.setup_help}</AlertDescription>
            </Alert>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={pending || previewPending}
              onClick={preview}
            >
              {previewPending ? '预览中…' : '预览最终地址'}
            </Button>
            {addressMode !== 'legacy_api_base' && (
              <Button
                type='button'
                variant='link'
                size='sm'
                onClick={showAdvanced}
              >
                接口前缀在高级设置中修改
              </Button>
            )}
          </div>
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
  invalidate,
}: {
  provider: ProviderModule
  pending: boolean
  invalidate: () => void
}) {
  const form = useFormContext<ChannelValues>()
  const addressMode = useWatch({ control: form.control, name: 'address_mode' })
  const customPrefix = useWatch({
    control: form.control,
    name: 'custom_prefix',
  })
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
          <p className='text-sm text-muted-foreground'>
            保存默认项不会发起测试或恢复健康。
          </p>
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
                <FormControl>
                  <Input
                    {...field}
                    type='number'
                    min={3}
                    max={60}
                    onChange={(event) => {
                      field.onChange(event.target.valueAsNumber)
                      invalidate()
                    }}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {addressMode !== 'legacy_api_base' && (
            <FormField
              control={form.control}
              name='custom_prefix'
              render={({ field }) => (
                <FormItem className='flex items-center justify-between gap-4'>
                  <div>
                    <FormLabel>自定义接口前缀</FormLabel>
                    <FormDescription>
                      关闭时使用供应商默认前缀。
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={(value) => {
                        field.onChange(value)
                        invalidate()
                      }}
                      disabled={pending}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          )}
          {addressMode !== 'legacy_api_base' && customPrefix && (
            <FormField
              control={form.control}
              name='api_prefix'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>接口前缀</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      onChange={(event) => {
                        field.onChange(event)
                        invalidate()
                      }}
                      placeholder='使用供应商默认前缀'
                    />
                  </FormControl>
                  <FormDescription>
                    相对路径，例如 /v1；留空明确使用裸服务根。
                  </FormDescription>
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
