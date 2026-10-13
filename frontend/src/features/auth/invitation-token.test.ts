import { expect, it } from 'vitest'
import { invitationToken } from './invitation-token'

it('accepts the fragment emitted in invitation emails and supports named fragments', () => {
  expect(invitationToken('#opaque-invitation-token')).toBe(
    'opaque-invitation-token'
  )
  expect(invitationToken('#token=opaque-invitation-token')).toBe(
    'opaque-invitation-token'
  )
  expect(invitationToken('')).toBeNull()
  expect(invitationToken('#unrelated=value')).toBeNull()
})
