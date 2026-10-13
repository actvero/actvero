import { useId, useState } from 'react'
import { z } from 'zod'
import { useForm, useFieldArray, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Plus, Trash2, ChevronDown, Plug } from 'lucide-react'
import { avatarDataUrl } from '@/lib/avatar-image'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
  CollapsibleSection,
} from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Separator } from '@/components/ui/separator'
import { AvatarEditor } from '@/components/avatar-editor'
import { MemberPicker } from '@/components/member-picker'
import { PasswordInput } from '@/components/password-input'
import { RequestError } from '@/components/request-state'
import { Choice } from './choice'
import {
  useReturnFocus,
  authNames,
  useMcp,
  serviceInput,
  type Service,
} from './shared'

const schema = z
  .object({
    usage_scope: z.enum(['administrators', 'selected', 'organization']),
    member_ids: z.array(z.string()).max(1000, '最多选择 1000 名成员'),
    connection_options: z.object({
      connect_timeout: z.number().int().min(1).max(120),
      request_timeout: z.number().int().min(1).max(600),
      total_timeout: z.number().int().min(1).max(900),
      reset_on_progress: z.boolean(),
      health_enabled: z.boolean(),
      health_interval: z.number().int().min(30).max(3600),
    }),
    name: z.string().trim().min(1, '请输入名称').max(100),
    description: z.string().trim().max(2000, '简介最多 2000 字符'),
    icon: z.string(),
    transport: z.enum(['http', 'sse']),
    url: z.string().trim(),
    auth_mode: z.enum(['none', 'organization', 'personal', 'oauth']),
    credential_fields: z.array(
      z.object({
        key: z.string(),
        label: z.string(),
        header: z.string(),
        bearer: z.boolean(),
      })
    ),
    credential_values: z.record(z.string(), z.string()),
    authorization_url: z.string().trim(),
    token_url: z.string().trim(),
    client_id: z.string().trim(),
    scopes: z.string().trim(),
  })
  .superRefine((v, ctx) => {
    if (v.usage_scope === 'selected' && !v.member_ids.length)
      ctx.addIssue({
        code: 'custom',
        path: ['member_ids'],
        message: '请选择至少一名成员，或改为仅管理员',
      })
    if (
      v.connection_options.total_timeout <
      Math.max(
        v.connection_options.connect_timeout,
        v.connection_options.request_timeout
      )
    )
      ctx.addIssue({
        code: 'custom',
        path: ['connection_options', 'total_timeout'],
        message: '最大总耗时不能小于连接超时或请求超时',
      })
    if (!/^https?:\/\//.test(v.url))
      ctx.addIssue({
        code: 'custom',
        path: ['url'],
        message: '请输入完整 HTTP(S) 服务地址',
      })
    if (['organization', 'personal'].includes(v.auth_mode)) {
      v.credential_fields.forEach((f, i) => {
        if (!f.label.trim())
          ctx.addIssue({
            code: 'custom',
            path: ['credential_fields', i, 'label'],
            message: '请输入输入框名称',
          })
        if (!f.header.trim())
          ctx.addIssue({
            code: 'custom',
            path: ['credential_fields', i, 'header'],
            message: '请输入请求头名称',
          })
      })
    }
    if (v.auth_mode === 'oauth')
      for (const k of ['authorization_url', 'token_url', 'client_id'] as const)
        if (!v[k])
          ctx.addIssue({ code: 'custom', path: [k], message: '此项必填' })
  })
type Values = z.infer<typeof schema>
type Format = 'bearer' | 'api-key' | 'custom'
function initialFormat(service?: Service): Format {
  const fields = service?.credential_fields || []
  if (fields.length > 1) return 'custom'
  if (
    !fields.length ||
    (fields[0].header.toLowerCase() === 'authorization' && fields[0].bearer)
  )
    return 'bearer'
  return fields[0].bearer ? 'custom' : 'api-key'
}
export function ServiceEditor({
  service,
  close,
  returnFocus,
}: {
  service?: Service
  returnFocus?: () => void
  close: () => void
}) {
  const formatId = useId()
  const restoreFocus = useReturnFocus(returnFocus)
  const { write, rememberSaved, discoverSaved } = useMcp()
  const [advanced, setAdvanced] = useState(false)
  const [pending, setPending] = useState(false)
  const [readingIcon, setReadingIcon] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [format, setFormat] = useState<Format>(() => initialFormat(service))
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      usage_scope:
        service?.audience === 'selected'
          ? service.member_ids?.length
            ? 'selected'
            : 'administrators'
          : 'organization',
      member_ids: service?.member_ids || [],
      connection_options: {
        connect_timeout: 30,
        request_timeout: 120,
        total_timeout: 300,
        reset_on_progress: false,
        health_enabled: false,
        health_interval: 60,
        ...service?.connection_options,
      },
      name: service?.name || '',
      description: service?.description || '',
      icon: service?.icon || '',
      transport: service?.transport === 'sse' ? 'sse' : 'http',
      url: service?.url || '',
      auth_mode: service?.auth_mode || 'none',
      credential_fields: service?.credential_fields || [],
      credential_values: {},
      authorization_url: service?.oauth?.authorization_url || '',
      token_url: service?.oauth?.token_url || '',
      client_id: service?.oauth?.client_id || '',
      scopes: service?.oauth?.scopes || '',
    },
  })
  const fields = useFieldArray({
    control: form.control,
    name: 'credential_fields',
  })
  const [mode, currentFields, usageScope] = useWatch({
    control: form.control,
    name: ['auth_mode', 'credential_fields', 'usage_scope'],
  })
  function selectFormat(value: string) {
    setFormat(value as Format)
    if (value === 'custom') return
    const first = form.getValues('credential_fields')[0]
    fields.replace([
      {
        key: first?.key || 'token',
        label: first?.label || 'API Key',
        header: value === 'bearer' ? 'Authorization' : 'X-API-Key',
        bearer: value === 'bearer',
      },
    ])
  }
  const text = (
    name:
      | 'name'
      | 'description'
      | 'url'
      | 'authorization_url'
      | 'token_url'
      | 'client_id'
      | 'scopes',
    label: string,
    placeholder?: string
  ) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input {...field} placeholder={placeholder} disabled={pending} />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  )
  async function submit(v: Values) {
    let values: Record<string, string> | undefined
    if (v.auth_mode === 'organization') {
      const definition = (fs: Values['credential_fields']) =>
        fs.map(({ key, header, bearer }) => ({ key, header, bearer }))
      const needsValues =
        !service?.configured ||
        service.auth_mode !== 'organization' ||
        service.url !== v.url ||
        service.transport !== v.transport ||
        JSON.stringify(definition(service.credential_fields || [])) !==
          JSON.stringify(definition(v.credential_fields))
      const replacing = v.credential_fields.some(
        (f) => v.credential_values[f.key]
      )
      if (needsValues || replacing) {
        let missing = false
        for (const f of v.credential_fields)
          if (!v.credential_values[f.key]) {
            missing = true
            form.setError(`credential_values.${f.key}`, {
              message: '请完整填写组织凭据',
            })
          }
        if (missing) return
        values = Object.fromEntries(
          v.credential_fields.map((f) => [f.key, v.credential_values[f.key]])
        )
      }
    }
    setPending(true)
    setError(null)
    try {
      const body = {
        ...(service ? serviceInput(service) : {}),
        name: v.name,
        connection_options: v.connection_options,
        description: v.description,
        icon: v.icon,
        transport: v.transport,
        url: v.url,
        enabled: service?.enabled || false,
        audience:
          v.usage_scope === 'organization' ? 'organization' : 'selected',
        member_ids: v.usage_scope === 'selected' ? v.member_ids : [],
        auth_mode: v.auth_mode,
        credential_fields: ['organization', 'personal'].includes(v.auth_mode)
          ? v.credential_fields
          : [],
        oauth:
          v.auth_mode === 'oauth'
            ? {
                authorization_url: v.authorization_url,
                token_url: v.token_url,
                client_id: v.client_id,
                scopes: v.scopes,
              }
            : null,
        ...(values ? { credential_values: values } : {}),
        ...(service ? { version: service.version } : {}),
      }
      const saved = await write<Service>(
        '/services' + (service ? '/' + service.id : ''),
        service ? 'PUT' : 'POST',
        body
      )
      form.reset()
      rememberSaved([saved])
      if (!saved.checked_at) void discoverSaved([saved])
      close()
    } catch (e) {
      setError(e)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v && !pending) close()
      }}
    >
      <DialogContent
        onCloseAutoFocus={restoreFocus}
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl'
        onPointerDownOutside={(e) => {
          if (form.formState.isDirty || pending) e.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle className='pe-6 break-words'>
            {service ? `编辑服务：${service.name}` : '添加 MCP 服务'}
          </DialogTitle>
          <DialogDescription className='sr-only'>
            配置服务地址和认证方式
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-7'
            onSubmit={form.handleSubmit(submit, (errors) => {
              if (errors.connection_options) setAdvanced(true)
            })}
          >
            <fieldset className='flex min-w-0 flex-col gap-4'>
              <legend className='mb-3 font-medium'>基本信息</legend>
              <Separator />
              <div className='flex items-center gap-4'>
                <FormField
                  control={form.control}
                  name='icon'
                  render={({ field }) => (
                    <FormItem className='shrink-0'>
                      <FormLabel className='sr-only'>MCP 服务头像</FormLabel>
                      <AvatarEditor
                        value={field.value}
                        fallback={<Plug className='size-6' />}
                        label='MCP 服务头像'
                        disabled={pending || readingIcon}
                        onChange={async (file) => {
                          setReadingIcon(true)
                          try {
                            field.onChange(
                              file ? await avatarDataUrl(file) : ''
                            )
                            form.clearErrors('icon')
                          } finally {
                            setReadingIcon(false)
                          }
                        }}
                      />
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className='grid min-w-0 flex-1 gap-4 sm:grid-cols-3'>
                  <div className='min-w-0'>
                    {text('name', '服务名称', '例如：企业文档')}
                  </div>
                  <div className='min-w-0 sm:col-span-2'>
                    {text('description', '简介', '描述这个服务能做什么')}
                  </div>
                </div>
              </div>
            </fieldset>
            <fieldset className='flex min-w-0 flex-col gap-4'>
              <legend className='mb-3 font-medium'>连接配置</legend>
              <Separator />
              <FormField
                control={form.control}
                name='transport'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>连接方式</FormLabel>
                    <FormControl>
                      <RadioGroup
                        variant='segmented'
                        value={field.value}
                        onValueChange={field.onChange}
                        disabled={pending}
                        aria-label='连接方式'
                      >
                        <RadioGroupItem variant='segmented' value='http'>
                          Streamable HTTP
                        </RadioGroupItem>
                        <RadioGroupItem variant='segmented' value='sse'>
                          SSE（旧版）
                        </RadioGroupItem>
                      </RadioGroup>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {text('url', '服务地址', 'https://example.com/mcp')}
            </fieldset>
            <fieldset className='flex min-w-0 flex-col gap-4'>
              <legend className='mb-3 font-medium'>身份认证</legend>
              <Separator />
              <FormField
                control={form.control}
                name='auth_mode'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>认证方式</FormLabel>
                    <FormControl>
                      <Choice
                        label='认证方式'
                        value={field.value}
                        disabled={pending}
                        options={authNames}
                        onChange={(v) => {
                          field.onChange(v)
                          form.setValue('credential_values', {})
                          if (
                            ['personal', 'organization'].includes(v) &&
                            !fields.fields.length
                          )
                            fields.append({
                              key: 'token',
                              label: 'API Key',
                              header: 'Authorization',
                              bearer: true,
                            })
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {['personal', 'organization'].includes(mode) && (
                <>
                  <div className='flex flex-col gap-2'>
                    <Label htmlFor={formatId}>凭据格式</Label>
                    <Choice
                      id={formatId}
                      label='凭据格式'
                      value={format}
                      onChange={selectFormat}
                      disabled={pending}
                      options={{
                        bearer: 'Bearer Token',
                        'api-key': 'API Key 请求头',
                        custom: '自定义凭据',
                      }}
                    />
                  </div>
                  {fields.fields.map((f, i) => (
                    <fieldset key={f.id} className='flex flex-col gap-3'>
                      {format === 'custom' && (
                        <legend className='mb-2 text-sm font-medium'>
                          凭据 {i + 1}
                        </legend>
                      )}
                      <div className='grid gap-4 sm:grid-cols-2'>
                        <div className='flex items-start gap-2'>
                          <FormField
                            control={form.control}
                            name={`credential_fields.${i}.label`}
                            render={({ field }) => (
                              <FormItem className='min-w-0 flex-1'>
                                <FormLabel>输入框名称</FormLabel>
                                <FormControl>
                                  <Input {...field} disabled={pending} />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                          {format === 'custom' && fields.fields.length > 1 && (
                            <Button
                              className='self-end'
                              type='button'
                              variant='ghost'
                              size='icon'
                              disabled={pending}
                              aria-label={`删除凭据 ${i + 1}`}
                              onClick={() => fields.remove(i)}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </div>
                        {format !== 'bearer' && (
                          <FormField
                            control={form.control}
                            name={`credential_fields.${i}.header`}
                            render={({ field }) => (
                              <FormItem>
                                <FormLabel>请求头名称</FormLabel>
                                <FormControl>
                                  <Input
                                    {...field}
                                    disabled={pending}
                                    placeholder='X-API-Key'
                                  />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        )}
                      </div>
                      {format === 'custom' && (
                        <FormField
                          control={form.control}
                          name={`credential_fields.${i}.bearer`}
                          render={({ field }) => (
                            <FormItem className='flex items-center gap-2'>
                              <FormControl>
                                <Checkbox
                                  checked={field.value}
                                  onCheckedChange={field.onChange}
                                  disabled={pending}
                                />
                              </FormControl>
                              <FormLabel>自动添加 Bearer</FormLabel>
                            </FormItem>
                          )}
                        />
                      )}
                      {mode === 'organization' && (
                        <FormField
                          control={form.control}
                          name={`credential_values.${f.key}`}
                          defaultValue=''
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>
                                {currentFields[i]?.label || '组织密钥'}
                              </FormLabel>
                              <FormControl>
                                <PasswordInput
                                  {...field}
                                  value={field.value || ''}
                                  disabled={pending}
                                  autoComplete='new-password'
                                  placeholder={
                                    service?.configured &&
                                    service.auth_mode === 'organization'
                                      ? '已配置；留空保留，输入则替换'
                                      : currentFields[i]?.bearer
                                        ? '只填 Token，无需 Bearer 前缀'
                                        : '输入组织共用的凭据'
                                  }
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}
                    </fieldset>
                  ))}
                  {format === 'custom' && (
                    <Button
                      className='self-start'
                      type='button'
                      variant='outline'
                      size='sm'
                      disabled={pending || fields.fields.length >= 10}
                      onClick={() =>
                        fields.append({
                          key:
                            'credential_' +
                            crypto.randomUUID().replace(/-/g, ''),
                          label: '',
                          header: 'X-API-Key',
                          bearer: false,
                        })
                      }
                    >
                      <Plus />
                      添加凭据
                    </Button>
                  )}
                  {mode === 'personal' && (
                    <p className='text-sm text-muted-foreground'>
                      成员连接时填写自己的凭据。
                    </p>
                  )}
                  {format === 'bearer' && (
                    <Collapsible>
                      <CollapsibleTrigger asChild>
                        <Button type='button' variant='ghost' size='sm'>
                          <ChevronDown />
                          查看发送方式
                        </Button>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <p className='py-2 text-sm text-muted-foreground'>
                          Authorization: Bearer &lt;填写的凭据&gt;
                        </p>
                      </CollapsibleContent>
                    </Collapsible>
                  )}
                </>
              )}
              {mode === 'oauth' && (
                <>
                  <div className='grid gap-4 sm:grid-cols-2'>
                    {text('client_id', '客户端 ID')}
                    {text('scopes', '授权范围（可选）')}
                  </div>
                  {text(
                    'authorization_url',
                    '授权地址',
                    'https://example.com/oauth/authorize'
                  )}
                  {text(
                    'token_url',
                    '令牌地址',
                    'https://example.com/oauth/token'
                  )}
                  <p className='text-sm text-muted-foreground'>
                    使用支持 PKCE 的公共客户端；成员连接时前往授权。
                  </p>
                </>
              )}
            </fieldset>
            <fieldset className='flex min-w-0 flex-col gap-4'>
              <legend className='mb-3 font-medium'>使用范围</legend>
              <Separator />
              <FormField
                control={form.control}
                name='usage_scope'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>可使用成员</FormLabel>
                    <FormControl>
                      <Choice
                        label='可使用成员'
                        value={field.value}
                        onChange={field.onChange}
                        disabled={pending}
                        options={{
                          administrators: '仅管理员',
                          selected: '指定成员',
                          organization: '组织全员',
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <p className='text-sm text-muted-foreground'>
                {usageScope === 'administrators'
                  ? '仅管理员可配置和测试，普通成员不可见。'
                  : '服务启用后，范围内成员可发现和使用；管理员始终可配置和测试。'}
                {usageScope !== 'administrators' &&
                  ['personal', 'oauth'].includes(mode) &&
                  ' 成员仍需连接自己的业务账号。'}
              </p>
              {usageScope === 'selected' && (
                <FormField
                  control={form.control}
                  name='member_ids'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>共享给成员</FormLabel>
                      <FormControl>
                        <MemberPicker
                          value={field.value}
                          onChange={field.onChange}
                          disabled={pending}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </fieldset>
            <CollapsibleSection
              title='高级设置'
              open={advanced}
              onOpenChange={setAdvanced}
            >
              <div className='flex flex-col gap-4'>
                <div className='grid gap-4 sm:grid-cols-3'>
                  {(
                    [
                      ['connect_timeout', '连接超时（秒）', 120],
                      ['request_timeout', '请求超时（秒）', 600],
                      ['total_timeout', '最大总耗时（秒）', 900],
                    ] as const
                  ).map(([key, label, max]) => (
                    <FormField
                      key={key}
                      control={form.control}
                      name={`connection_options.${key}`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>{label}</FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              type='number'
                              min={1}
                              max={max}
                              onChange={(e) =>
                                field.onChange(
                                  e.target.value === ''
                                    ? NaN
                                    : Number(e.target.value)
                                )
                              }
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ))}
                </div>
                <FormField
                  control={form.control}
                  name='connection_options.reset_on_progress'
                  render={({ field }) => (
                    <FormItem className='flex items-center gap-2'>
                      <FormControl>
                        <Checkbox
                          checked={field.value}
                          onCheckedChange={(v) => field.onChange(v === true)}
                        />
                      </FormControl>
                      <FormLabel>收到工具进度通知时延长等待</FormLabel>
                    </FormItem>
                  )}
                />
                <p className='text-sm text-muted-foreground'>
                  延长等待仍受最大总耗时限制，超时不会自动重跑工具。
                </p>
                <Separator />
                <FormField
                  control={form.control}
                  name='connection_options.health_enabled'
                  render={({ field }) => (
                    <FormItem className='flex items-center gap-2'>
                      <FormControl>
                        <Checkbox
                          checked={field.value}
                          onCheckedChange={(v) => field.onChange(v === true)}
                        />
                      </FormControl>
                      <FormLabel>启用健康检查与自动恢复</FormLabel>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name='connection_options.health_interval'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>检查间隔（秒）</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type='number'
                          min={30}
                          max={3600}
                          onChange={(e) =>
                            field.onChange(
                              e.target.value === ''
                                ? NaN
                                : Number(e.target.value)
                            )
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <p className='text-sm text-muted-foreground'>
                  仅检查已启用服务的连接；连续失败会逐步延长间隔。个人凭据独立检查，关闭页面后仍继续。
                </p>
              </div>
            </CollapsibleSection>
            {!!error && <RequestError error={error} />}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                onClick={close}
                disabled={pending}
              >
                取消
              </Button>
              <Button disabled={pending || readingIcon}>
                {pending ? '保存中…' : '保存配置'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
