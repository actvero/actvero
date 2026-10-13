// Only internal page URLs may survive a login round trip. Keep the same
// restrictions as backend/app/modules/auth/return_to.py.
export function loginReturnTo(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 2048 ||
    [...value].some((character) => {
      const code = character.charCodeAt(0)
      return code <= 32 || code === 127
    })
  )
    return '/console'
  const path = value.split(/[?#]/, 1)[0]
  if (
    !/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]*$/.test(path) ||
    /^\/(?:api|login)(?:\/|$)/.test(path)
  )
    return '/console'
  return path === '/' ? '/console' : value
}
