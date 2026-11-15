import { dateTime, type Schema } from '@/lib/api'

export type Application = Schema['ApplicationView']
export type ApplicationKey = Schema['ApplicationKeyView']
export const applications = '/integrations/applications'

export const applicationPermissions = [
  {
    name: '模型',
    read: 'models_enabled',
    write: 'models_write_enabled',
    description: '读取目录和参数 · 发起模型调用',
  },
  {
    name: 'MCP',
    read: 'mcp_enabled',
    write: 'mcp_write_enabled',
    description: '发现和调用已开放服务 · 创建与更新服务配置',
  },
  {
    name: 'Skills',
    read: 'skills_enabled',
    write: 'skills_write_enabled',
    description: '查看和下载已发布技能 · 上传版本草稿',
  },
  {
    name: '专家',
    read: 'experts_enabled',
    write: 'experts_write_enabled',
    description: '读取已发布专家及依赖 · 创建与编辑草稿',
  },
  {
    name: '知识库',
    read: 'knowledge_enabled',
    write: 'knowledge_write_enabled',
    description: '检索和阅读资料 · 管理应用自建库',
  },
] as const

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
    models_write_enabled: app.models_write_enabled,
    mcp_write_enabled: app.mcp_write_enabled,
    skills_write_enabled: app.skills_write_enabled,
    experts_write_enabled: app.experts_write_enabled,
    knowledge_write_enabled: app.knowledge_write_enabled,
  }
}
