import type { Schema } from '@/lib/api'

export function sourceBox(source: Schema['SourceLocation']) {
  const box = source.bbox
  if (!box || box.length !== 4 || !box.every(Number.isFinite)) return null
  const width = source.coordinate_space === 'normalized' ? 1 : source.page_width
  const height =
    source.coordinate_space === 'normalized' ? 1 : source.page_height
  if (
    source.coordinate_space === 'unknown' ||
    !width ||
    !height ||
    width <= 0 ||
    height <= 0
  )
    return null
  const [x1, y1, x2, y2] = [
    box[0] / width,
    box[1] / height,
    box[2] / width,
    box[3] / height,
  ]
  if (x1 < 0 || y1 < 0 || x2 > 1 || y2 > 1 || x2 <= x1 || y2 <= y1) return null
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${(x2 - x1) * 100}%`,
    height: `${(y2 - y1) * 100}%`,
  }
}

export function textSegments(
  text: string,
  ranges: Schema['OriginalTextRange'][]
) {
  // API offsets count Unicode code points, which differs from JavaScript UTF-16 for emoji.
  const chars = Array.from(text.replace(/^\uFEFF/, ''))
  const merged: { start: number; end: number }[] = []
  for (const range of [...ranges].sort((a, b) => a.start - b.start)) {
    if (range.start < 0 || range.end > chars.length || range.end <= range.start)
      continue
    const previous = merged.at(-1)
    if (previous && previous.end >= range.start)
      previous.end = Math.max(previous.end, range.end)
    else merged.push({ ...range })
  }
  const segments: { text: string; highlighted: boolean; start: number }[] = []
  let offset = 0
  for (const range of merged) {
    if (range.start > offset)
      segments.push({
        text: chars.slice(offset, range.start).join(''),
        highlighted: false,
        start: offset,
      })
    segments.push({
      text: chars.slice(range.start, range.end).join(''),
      highlighted: true,
      start: range.start,
    })
    offset = range.end
  }
  if (offset < chars.length)
    segments.push({
      text: chars.slice(offset).join(''),
      highlighted: false,
      start: offset,
    })
  return segments
}
