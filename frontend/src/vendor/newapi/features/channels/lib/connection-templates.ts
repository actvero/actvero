/* Actvero route presets for the native Advanced Custom channel. */
import type { ChannelFormValues } from './channel-form'

export const ARK_AGENT_PLAN_TEMPLATE = 'volcengine-agent-plan' as const
export const ARK_AGENT_PLAN_ORIGIN = 'https://ark.cn-beijing.volces.com'
export const ARK_AGENT_PLAN_LABEL = '火山 Agent Plan'

export const ARK_AGENT_PLAN_CONFIG = {
  advanced_routes: [
    {
      incoming_path: '/v1/chat/completions',
      upstream_path: '/api/plan/v3/chat/completions',
      converter: 'none',
    },
    {
      incoming_path: '/v1/messages',
      upstream_path: '/api/plan/v1/messages',
      converter: 'none',
    },
    {
      incoming_path: '/v1/responses',
      upstream_path: '/api/plan/v3/chat/completions',
      converter: 'openai_responses_to_openai_chat_completions',
    },
  ],
}

export function isArkAgentPlanTemplate(
  values: Pick<ChannelFormValues, 'type' | 'base_url' | 'advanced_custom'>
): boolean {
  if (values.type !== 58 || values.base_url !== ARK_AGENT_PLAN_ORIGIN)
    return false
  try {
    const routes = JSON.parse(values.advanced_custom || '{}').advanced_routes
    return (
      Array.isArray(routes) &&
      routes.length === ARK_AGENT_PLAN_CONFIG.advanced_routes.length &&
      ARK_AGENT_PLAN_CONFIG.advanced_routes.every((expected) =>
        routes.some(
          (route) =>
            route.incoming_path === expected.incoming_path &&
            route.upstream_path === expected.upstream_path &&
            (route.converter || 'none') === expected.converter &&
            !route.models?.length
        )
      )
    )
  } catch {
    return false
  }
}
