export const memberOperations = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
  image_generation: '图片生成',
  speech: '语音合成',
  transcription: '语音转文字',
} as const

export type MyModelSearch = {
  q: string
  operation: keyof typeof memberOperations | ''
  page: number
}

/** Sanitize URL state before it reaches the member directory API. */
export function readMyModelSearch(
  search: Record<string, unknown>
): MyModelSearch {
  const q = typeof search.q === 'string' ? search.q.trim().slice(0, 80) : ''
  const operation =
    typeof search.operation === 'string' &&
    Object.prototype.hasOwnProperty.call(memberOperations, search.operation)
      ? (search.operation as keyof typeof memberOperations)
      : ''
  const page = Number(search.page)
  return {
    q,
    operation,
    page: Number.isSafeInteger(page) && page >= 1 ? page : 1,
  }
}
