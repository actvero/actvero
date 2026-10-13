// Accept the existing mail format (#secret) and named fragments (#token=secret).
// Fragment credentials are claimed into the HttpOnly session, never URL queries.
export function invitationToken(hash: string): string | null {
  const fragment = hash.replace(/^#/, '')
  return (
    (fragment.includes('=')
      ? new URLSearchParams(fragment).get('token')
      : fragment) || null
  )
}
