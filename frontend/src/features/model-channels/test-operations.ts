export const operationLabels = {
  chat: '对话',
  embedding: '文本向量',
  rerank: '重排',
  image_generation: '图片生成',
  speech: '语音合成',
}
export type TestOperation = keyof typeof operationLabels

export function meterLabel(
  operation: string,
  usage: {
    input_tokens?: number | null
    output_tokens?: number | null
    search_units?: number | null
    image_count?: number | null
    audio_duration_ms?: number | null
  }
) {
  if (operation === 'speech')
    return `输出音频 ${usage.audio_duration_ms ?? '未知'} ms（文件测量） · 上游用量未知`
  const input = `输入 ${usage.input_tokens ?? '未知'} Token`
  if (operation === 'image_generation')
    return `图片 ${usage.image_count ?? '未知'} 张 · ${input} / 输出 ${usage.output_tokens ?? '未知'} Token`
  if (operation === 'chat')
    return `${input} / 输出 ${usage.output_tokens ?? '未知'} Token`
  if (operation === 'rerank')
    return `${input} · 搜索单位 ${usage.search_units ?? '未知'}`
  return input
}
