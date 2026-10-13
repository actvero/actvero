export type InputSchema = {
  type?: string | string[]
  title?: string
  description?: string
  default?: unknown
  properties?: Record<string, InputSchema>
  required?: string[]
  anyOf?: InputSchema[]
  items?: InputSchema
  enum?: unknown[]
  [key: string]: unknown
}
export const baseType = (s: InputSchema) =>
  Array.isArray(s.type) ? s.type.find((t) => t !== 'null') : s.type
export const nullable = (s: InputSchema) =>
  Array.isArray(s.type) && s.type.includes('null')
// Distinct types can be selected without guessing between overlapping branches.
// Keep references, conditional schemas and same-type unions in JSON mode.
export function formVariants(s: InputSchema): InputSchema[] | null {
  if (
    !Array.isArray(s.anyOf) ||
    s.anyOf.length < 2 ||
    s.anyOf.length > 8 ||
    ['type', 'properties', 'items', 'enum'].some((key) => key in s)
  )
    return null
  const types = s.anyOf.map((branch) =>
    branch && typeof branch.type === 'string' ? branch.type : null
  )
  if (
    types.some((t) => !t) ||
    new Set(types).size !== types.length ||
    (types.includes('number') && types.includes('integer'))
  )
    return null
  return s.anyOf.map((branch) => ({ description: s.description, ...branch }))
}
export function fieldInitialValue(s: InputSchema): unknown {
  if ('default' in s) return s.default
  return baseType(s) === 'object'
    ? {}
    : baseType(s) === 'array'
      ? []
      : baseType(s) === 'boolean'
        ? false
        : baseType(s) === 'null'
          ? null
          : ''
}

export function supportsForm(s: InputSchema, depth = 0): boolean {
  if (
    depth > 8 ||
    [
      '$ref',
      'oneOf',
      'allOf',
      'if',
      'patternProperties',
      'prefixItems',
      'dependentSchemas',
    ].some((k) => k in s)
  )
    return false
  if ('anyOf' in s) {
    const branches = formVariants(s)
    return (
      depth > 0 &&
      !!branches &&
      branches.every((branch) => supportsForm(branch, depth + 1))
    )
  }
  if (Array.isArray(s.type) && s.type.filter((t) => t !== 'null').length !== 1)
    return false
  const t = baseType(s)
  if (t === 'object')
    return Object.values(s.properties ?? {}).every(
      (p) => typeof p === 'object' && p !== null && supportsForm(p, depth + 1)
    )
  if (t === 'array')
    return (
      !!s.items &&
      typeof s.items === 'object' &&
      !Array.isArray(s.items) &&
      supportsForm(s.items, depth + 1)
    )
  return (
    ['string', 'number', 'integer', 'boolean', 'null'].includes(t ?? '') &&
    (!s.enum ||
      s.enum.every(
        (v) => v === null || ['string', 'number', 'boolean'].includes(typeof v)
      ))
  )
}
export function schemaDefaults(s: InputSchema): unknown {
  if ('default' in s) return s.default
  if (baseType(s) === 'object')
    return Object.fromEntries(
      Object.entries(s.properties ?? {}).flatMap(([k, p]) => {
        const v = 'default' in p ? p.default : undefined
        return v === undefined ? [] : [[k, v]]
      })
    )
  return undefined
}
export function parseArguments(json: string): Record<string, unknown> {
  let value: unknown
  try {
    value = JSON.parse(json)
  } catch {
    throw Error('JSON 格式无效，请检查括号、逗号和引号')
  }
  if (!value || Array.isArray(value) || typeof value !== 'object')
    throw Error('参数必须为 JSON 对象')
  return value as Record<string, unknown>
}
export function validateRequired(
  schema: InputSchema,
  value: unknown,
  path = '',
  checkRequired = true
): string | null {
  const branches = formVariants(schema)
  if (branches) {
    return branches.some(
      (branch) => !validateRequired(branch, value, path, checkRequired)
    )
      ? null
      : `参数 ${path.replace(/\.$/, '')} 不符合可选输入类型`
  }
  if (value === null && nullable(schema)) return null
  const t = baseType(schema)
  if (
    (t === 'null' && value !== null) ||
    (t === 'string' && typeof value !== 'string') ||
    (t === 'boolean' && typeof value !== 'boolean') ||
    ((t === 'number' || t === 'integer') &&
      (typeof value !== 'number' ||
        !Number.isFinite(value) ||
        (t === 'integer' && !Number.isInteger(value)))) ||
    (t === 'array' && !Array.isArray(value)) ||
    (t === 'object' &&
      (!value || typeof value !== 'object' || Array.isArray(value)))
  )
    return `参数 ${path.replace(/\.$/, '')} 类型不正确`
  if (schema.enum && !schema.enum.includes(value))
    return `请选择参数 ${path.replace(/\.$/, '')} 的有效选项`
  if (baseType(schema) === 'object' && value && typeof value === 'object') {
    const object = value as Record<string, unknown>
    for (const key of checkRequired ? (schema.required ?? []) : [])
      if (object[key] === undefined) return `请填写必填参数 ${path}${key}`
    for (const [key, s] of Object.entries(schema.properties ?? {}))
      if (object[key] !== undefined) {
        const error = validateRequired(
          s,
          object[key],
          `${path}${key}.`,
          checkRequired
        )
        if (error) return error
      }
  }
  if (baseType(schema) === 'array' && Array.isArray(value) && schema.items)
    for (const [i, v] of value.entries()) {
      const error = validateRequired(
        schema.items,
        v,
        `${path}${i}.`,
        checkRequired
      )
      if (error) return error
    }
  return null
}
