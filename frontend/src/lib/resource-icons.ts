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

export function selectedIcon(
  value: IconSelection,
  options: IconOption[],
  automaticImage?: string
) {
  if (value.source === 'library')
    return options.find((icon) => icon.key === value.key)?.image
  return value.source === 'upload' ? value.image : automaticImage
}
