import { BrandMark } from '@/features/branding/brand'

// Compatibility wrapper: every platform placement consumes the shared brand.
export function PlatformLogo(_props: { url?: string | null }) {
  return <BrandMark />
}
