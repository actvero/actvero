export type ChannelFilters = {
  q: string
  model: string
  state: string
  type: string
  group: string
  sort: string
  order: string
}
export const initialChannelFilters: ChannelFilters = {
  q: '',
  model: '',
  state: 'all',
  type: 'all',
  group: 'all',
  sort: 'priority',
  order: 'desc',
}
