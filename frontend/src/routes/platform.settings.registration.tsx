import { createFileRoute } from '@tanstack/react-router'
import { RegistrationSettingsPage } from '@/features/platform/registration-settings-page'

export const Route = createFileRoute('/platform/settings/registration')({
  component: RegistrationSettingsPage,
})
