import aihubmix from '@/assets/provider-avatars/aihubmix.webp?no-inline'
import anthropic from '@/assets/provider-avatars/anthropic.webp?no-inline'
import aws from '@/assets/provider-avatars/aws.webp?no-inline'
import azure from '@/assets/provider-avatars/azure.webp?no-inline'
import bailian from '@/assets/provider-avatars/bailian.webp?no-inline'
import deepseek from '@/assets/provider-avatars/deepseek.webp?no-inline'
import gemini from '@/assets/provider-avatars/gemini.webp?no-inline'
import groq from '@/assets/provider-avatars/groq.webp?no-inline'
import minimax from '@/assets/provider-avatars/minimax.webp?no-inline'
import mistral from '@/assets/provider-avatars/mistral.webp?no-inline'
import moonshot from '@/assets/provider-avatars/moonshot.webp?no-inline'
import ollama from '@/assets/provider-avatars/ollama.webp?no-inline'
import openai from '@/assets/provider-avatars/openai.webp?no-inline'
import openrouter from '@/assets/provider-avatars/openrouter.webp?no-inline'
import siliconcloud from '@/assets/provider-avatars/siliconcloud.webp?no-inline'
import volcengine from '@/assets/provider-avatars/volcengine.webp?no-inline'
import xai from '@/assets/provider-avatars/xai.webp?no-inline'
import zhipu from '@/assets/provider-avatars/zhipu.webp?no-inline'
import type { AvatarPresetPicker } from '@/components/avatar-presets'

// Display assets only: this catalog never selects a protocol or alters credentials.
export const providerAvatarPicker: AvatarPresetPicker = {
  title: '选择厂商图标',
  description: '选择图标后预览，保存渠道时生效。仅更换头像，不修改连接配置。',
  options: [
    {
      id: 'openai',
      name: 'OpenAI',
      image: openai,
      keywords: ['GPT', 'ChatGPT'],
    },
    {
      id: 'anthropic',
      name: 'Anthropic',
      image: anthropic,
      keywords: ['Claude'],
    },
    { id: 'gemini', name: 'Google Gemini', image: gemini, keywords: ['谷歌'] },
    {
      id: 'deepseek',
      name: 'DeepSeek',
      image: deepseek,
      keywords: ['深度求索'],
    },
    {
      id: 'bailian',
      name: '阿里百炼',
      image: bailian,
      keywords: ['Alibaba', 'Qwen', '通义千问', 'DashScope'],
    },
    {
      id: 'volcengine',
      name: '火山方舟',
      image: volcengine,
      keywords: ['Volcengine', 'Ark', '豆包', 'Doubao'],
    },
    {
      id: 'moonshot',
      name: 'Moonshot',
      image: moonshot,
      keywords: ['Kimi', '月之暗面'],
    },
    {
      id: 'zhipu',
      name: '智谱',
      image: zhipu,
      keywords: ['Zhipu', 'GLM', 'Z.ai'],
    },
    { id: 'minimax', name: 'MiniMax', image: minimax, keywords: ['海螺'] },
    {
      id: 'siliconcloud',
      name: '硅基流动',
      image: siliconcloud,
      keywords: ['SiliconFlow', 'SiliconCloud'],
    },
    { id: 'openrouter', name: 'OpenRouter', image: openrouter },
    { id: 'aihubmix', name: 'AIHubMix', image: aihubmix },
    {
      id: 'azure',
      name: 'Azure',
      image: azure,
      keywords: ['Microsoft', '微软'],
    },
    {
      id: 'aws',
      name: 'AWS',
      image: aws,
      keywords: ['Amazon', 'Bedrock', '亚马逊'],
    },
    { id: 'mistral', name: 'Mistral', image: mistral },
    { id: 'groq', name: 'Groq', image: groq },
    { id: 'xai', name: 'xAI', image: xai, keywords: ['Grok'] },
    { id: 'ollama', name: 'Ollama', image: ollama, keywords: ['本地'] },
  ],
}
