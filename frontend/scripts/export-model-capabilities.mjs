// Generated capabilities are runtime data, never a replacement for upstream /models.
import { writeFileSync } from 'node:fs'
import { builtinProviders, getBuiltinModels } from '@earendil-works/pi-ai/providers/all'
const models = builtinProviders().flatMap(({id}) => getBuiltinModels(id).filter(m => m.type === 'chat').map(m => ({
  provider: id, id: m.id, api: m.api, context_window: m.contextWindow, max_output: m.maxTokens,
  reasoning: m.reasoning, input: m.input, thinking: m.thinkingLevelMap ?? {},
  compat: Object.fromEntries(Object.entries(m.compat ?? {}).filter(([k]) => ['supportsReasoningEffort', 'thinkingFormat', 'maxTokensField', 'supportsDeveloperRole', 'supportsToolChoice'].includes(k))),
}))).sort((a,b) => `${a.provider}/${a.id}`.localeCompare(`${b.provider}/${b.id}`, 'en'))
// DSH's native DeepSeek adapter adds the current V4 models beyond the pi catalog.
// Source: deepseek-ai/deepseek-harness, dsh-v0.2.1-rc.2 (MIT).
for (const id of ['deepseek-flash', 'deepseek-v4-pro']) {
  for (let i = models.length - 1; i >= 0; i--) if (models[i].provider === 'deepseek' && models[i].id === id) models.splice(i, 1)
  models.push({provider: 'deepseek', id, api: 'openai-completions', context_window: 1000000, max_output: 256000,
    reasoning: true, input: id === 'deepseek-flash' ? ['text', 'image'] : ['text'],
    thinking: {off: 'off', minimal: null, low: 'low', medium: null, high: 'high', xhigh: null, max: 'max'}, compat: {},
    source_version: 'dsh-v0.2.1-rc.2'})
}
writeFileSync(new URL('../../backend/app/modules/model_gateway/data/model-capabilities.json', import.meta.url), JSON.stringify({source: '@earendil-works/pi-ai', version: '1.1.0', models}, null, 2) + '\n')
console.log(`Exported ${models.length} capability records`)
