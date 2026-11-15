import { Inflate } from 'fflate'

const MiB = 1024 * 1024
const invalid = () => new Error('文档压缩结构无法读取')
const nameDecoder = new TextDecoder('utf-8', { fatal: true })

/** Index first, then read only the OOXML parts the viewer actually needs. */
export function officePackage(bytes: ArrayBuffer) {
  if (bytes.byteLength > 20 * MiB) throw new Error('原件超过 20 MiB')
  const data = new Uint8Array(bytes)
  const view = new DataView(bytes)
  const u16 = (p: number) => view.getUint16(p, true)
  const u32 = (p: number) => view.getUint32(p, true)
  let end = data.length - 22
  // File size and entry limits put this format well inside single-volume ZIP.
  while (
    end >= Math.max(0, data.length - 65557) &&
    (u32(end) !== 0x06054b50 || end + 22 + u16(end + 20) !== data.length)
  )
    end--
  if (end < Math.max(0, data.length - 65557)) throw invalid()
  const count = u16(end + 10)
  const start = u32(end + 16)
  if (
    u16(end + 4) ||
    u16(end + 6) ||
    u16(end + 8) !== count ||
    !count ||
    count > 3000 ||
    start + u32(end + 12) !== end
  )
    throw invalid()

  const entries = new Map<
    string,
    { offset: number; method: number; size: number; packed: number }
  >()
  let cursor = start
  let sizeSum = 0
  for (let i = 0; i < count; i++) {
    if (cursor + 46 > end || u32(cursor) !== 0x02014b50) throw invalid()
    const flags = u16(cursor + 8)
    const method = u16(cursor + 10)
    const packed = u32(cursor + 20)
    const size = u32(cursor + 24)
    const nameStart = cursor + 46
    const nameEnd = nameStart + u16(cursor + 28)
    const local = u32(cursor + 42)
    cursor = nameEnd + u16(cursor + 30) + u16(cursor + 32)
    if (
      cursor > end ||
      local + 30 > start ||
      u32(local) !== 0x04034b50 ||
      flags & 1
    )
      throw invalid()
    const name = nameDecoder.decode(data.subarray(nameStart, nameEnd))
    if (
      !name ||
      name.startsWith('/') ||
      name.includes('\\') ||
      Array.from(name).some((char) => char.charCodeAt(0) < 32) ||
      name.split('/').includes('..') ||
      entries.has(name) ||
      u16(local + 8) !== method ||
      u16(local + 6) & 1
    )
      throw invalid()
    const offset = local + 30 + u16(local + 26) + u16(local + 28)
    if (offset + packed > start || (method === 0 && packed !== size))
      throw invalid()
    sizeSum += size
    if (sizeSum > 100 * MiB) throw new Error('文档解包内容超过 100 MiB')
    entries.set(name, { offset, method, size, packed })
  }
  if (cursor !== end) throw invalid()

  return {
    read(name: string) {
      const entry = entries.get(name)
      if (!entry) return undefined
      if (entry.size > 16 * MiB) throw new Error('文档内部文件超过 16 MiB')
      const input = data.subarray(entry.offset, entry.offset + entry.packed)
      if (entry.method === 0) return input
      if (entry.method !== 8 || !input.length) throw invalid()
      const out = new Uint8Array(entry.size)
      let written = 0
      const decoder = new Inflate((part) => {
        if (written + part.length > out.length) throw invalid()
        out.set(part, written)
        written += part.length
      })
      // Bound the output of each push, even if declared sizes are false.
      for (let p = 0; p < input.length; p += 512)
        decoder.push(input.subarray(p, p + 512), p + 512 >= input.length)
      if (written !== out.length) throw invalid()
      return out
    },
  }
}
