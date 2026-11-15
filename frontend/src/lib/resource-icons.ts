import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type IconSelection = {
  source: 'auto' | 'library' | 'upload'
  key?: string
  image?: string
}

export type IconOption = {
  key: string
  label: string
  category: string
  image: string
}

export function useResourceIconCatalog(enabled: boolean) {
  const { organization, user } = useOrganization()
  return useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'skills',
      'icon-catalog',
    ],
    queryFn: () => api<IconOption[]>('/skills/icon-catalog'),
    staleTime: Infinity,
    enabled,
  })
}

export function selectedIcon(
  value: IconSelection,
  options: IconOption[],
  automaticImage?: string
) {
  if (value.source === 'library')
    return options.find((icon) => icon.key === value.key)?.image
  return value.source === 'upload' ? value.image : automaticImage
}
