import { Network } from 'lucide-react'
import type { Schema } from '@/lib/api'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { healthLabels } from './api'
import { providerImage, useProviderModules } from './provider-modules'

export type Channel = Schema['ChannelView']
export type Detail = Schema['ChannelDetail']
export type Discovery = Schema['DiscoveryView']

export function ManualBadge({ channel }: { channel: Channel }) {
  return (
    <Badge variant={channel.manual_enabled ? 'success' : 'secondary'}>
      {channel.manual_enabled ? '已启用' : '已停用'}
    </Badge>
  )
}

export function HealthBadge({ channel }: { channel: Channel }) {
  const state = channel.archived
    ? 'not_applicable'
    : channel.health_summary?.state
  return (
    <Badge
      title='绑定健康汇总；成员调用还取决于渠道开关和授权'
      variant={
        state === 'ready'
          ? 'success'
          : state === 'unavailable' || state === 'degraded'
            ? 'destructive'
            : 'outline'
      }
    >
      {state ? healthLabels[state] : '健康待读取'}
    </Badge>
  )
}

export function ChannelAvatar({ channel }: { channel: Channel }) {
  const providers = useProviderModules()
  const provider = providers.data?.find((item) => item.id === channel.provider)
  return (
    <Avatar>
      <AvatarImage src={channel.icon || providerImage(provider)} alt='' />
      <AvatarFallback>
        <Network className='size-4' />
      </AvatarFallback>
    </Avatar>
  )
}

export function CheckBadge({ channel }: { channel: Channel }) {
  if (channel.archived) return <Badge variant='secondary'>已归档</Badge>
  if (!channel.last_check)
    return (
      <Badge variant='outline' dot>
        未检查
      </Badge>
    )
  return (
    <Badge variant={channel.last_check.ok ? 'success' : 'destructive'} dot>
      {channel.last_check.ok ? '目录读取成功' : '目录读取失败'}
    </Badge>
  )
}
