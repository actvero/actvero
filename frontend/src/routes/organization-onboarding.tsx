import { createFileRoute } from '@tanstack/react-router'
import { OrganizationOnboardingPage } from '@/features/platform/organization-onboarding-page'

export const Route = createFileRoute('/organization-onboarding')({
  component: OrganizationOnboardingPage,
})
