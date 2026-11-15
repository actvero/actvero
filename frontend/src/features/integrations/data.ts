import { dateTime, type Schema } from '@/lib/api'

export type Application = Schema['ApplicationView']
export type ApplicationKey = Schema['ApplicationKeyView']
export const applications = '/integrations/applications'

export const timestamp = (value?: string | null) =>
  value ? dateTime(value) : '—'

export function applicationSettings(
  app: Application
): Schema['ApplicationUpdate'] {
  return {
    name: app.name,
    enabled: app.enabled,
    version: app.version,
    models_enabled: app.models_enabled,
    mcp_enabled: app.mcp_enabled,
    skills_enabled: app.skills_enabled,
    experts_enabled: app.experts_enabled,
    knowledge_enabled: app.knowledge_enabled,
  }
}
