import {
  Users,
  UserRound,
  Plug,
  Network,
  KeyRound,
  Gauge,
  PackageOpen,
  Settings,
  Bot,
  LayoutDashboard,
  LayoutTemplate,
} from 'lucide-react'
import type { NavGroup } from '../types'

export function navigation(
  admin: boolean,
  instanceAdministrator = false
): NavGroup[] {
  return [
    {
      title: '工作台',
      items: [{ title: '概览', url: '/overview', icon: LayoutDashboard }],
    },
    ...(admin
      ? [
          {
            title: '能力管理',
            items: [
              { title: '专家', icon: Bot, url: '/experts' },
              {
                title: '模型网关',
                icon: Network,
                items: [
                  { title: '数据看板', url: '/llm-usage' },
                  { title: '渠道', url: '/model-channels' },
                  { title: '模型', url: '/models' },
                  { title: '额度策略', url: '/quota-policies' },
                  { title: '调用记录', url: '/llm-calls' },
                ],
              },
              {
                title: 'Skills',
                icon: PackageOpen,
                items: [
                  { title: '技能', url: '/skills' },
                  { title: '分发记录', url: '/skill-distributions' },
                ],
              },
              {
                title: 'MCP',
                icon: Plug,
                items: [
                  { title: '服务', url: '/mcp' },
                  { title: '调用记录', url: '/mcp-calls' },
                  { title: '连接日志', url: '/mcp-logs' },
                ],
              },
              { title: '工作台', icon: LayoutTemplate, url: '/workbenches' },
            ],
          },
          {
            title: '管理',
            items: [
              {
                title: '组织管理',
                icon: Users,
                items: [
                  { title: '组织设置', url: '/organization-settings' },
                  { title: '成员管理', url: '/users' },
                  { title: '操作记录', url: '/audit' },
                  { title: '密钥管理', url: '/access-keys' },
                ],
              },
              ...(instanceAdministrator
                ? [
                    {
                      title: '系统设置',
                      icon: Settings,
                      items: [
                        { title: '品牌形象', url: '/system/general' },
                        { title: '门户设置', url: '/system/portal' },
                        { title: '客户端版本', url: '/system/downloads' },
                        { title: 'CLI 接入', url: '/system/cli' },
                        { title: '邮件服务', url: '/system/mail' },
                        { title: '对象存储', url: '/system/storage' },
                        { title: '邮件模板', url: '/system/templates' },
                      ],
                    },
                  ]
                : []),
            ],
          },
        ]
      : [
          {
            title: '能力管理',
            items: [
              {
                title: 'MCP',
                icon: Plug,
                items: [{ title: '可用服务', url: '/mcp' }],
              },
            ],
          },
        ]),
    {
      title: '个人',
      items: [
        { title: '个人设置', url: '/account', icon: UserRound },
        { title: '我的模型', url: '/my-models', icon: Network },
        { title: '我的用量', url: '/my-usage', icon: Gauge },
        { title: '访问密钥', url: '/my-access-keys', icon: KeyRound },
      ],
    },
  ]
}

export function platformNavigation(): NavGroup[] {
  return [
    {
      title: '平台运营',
      items: [
        {
          title: '组织',
          icon: Users,
          items: [
            { title: '组织管理', url: '/platform/organizations' },
            { title: '开通邀请', url: '/platform/invitations' },
            { title: '开通申请', url: '/platform/applications' },
          ],
        },
        {
          title: '站点与品牌',
          icon: Settings,
          items: [
            { title: '品牌形象', url: '/platform/settings/general' },
            { title: '门户设置', url: '/platform/settings/portal' },
            { title: '客户端版本', url: '/platform/settings/downloads' },
          ],
        },
        {
          title: '设置',
          icon: Settings,
          items: [
            { title: '注册与开通', url: '/platform/settings/registration' },
            { title: 'CLI 接入', url: '/platform/settings/cli' },
            { title: '邮件服务', url: '/platform/settings/mail' },
            { title: '对象存储', url: '/platform/settings/storage' },
            { title: '邮件模板', url: '/platform/settings/templates' },
          ],
        },
      ],
    },
  ]
}
