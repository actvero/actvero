import type { SessionState, Store, Tokens } from '../src/store.js';
import { READ_SCOPE } from '../src/client.js';
export class MemoryStore implements Store {
  state: SessionState = {};
  writes: SessionState[] = [];
  failSave?: (value: SessionState) => boolean;
  async load() {
    return structuredClone(this.state);
  }
  async save(value: SessionState) {
    if (this.failSave?.(value)) throw new Error('store unavailable');
    this.state = structuredClone(value);
    this.writes.push(structuredClone(value));
  }
  async clear() {
    this.state = {};
  }
  async locked<T>(action: () => Promise<T>) {
    return action();
  }
}
export function tokens(scope = READ_SCOPE, suffix = 'fixture'): Tokens {
  return {
    access_token: 'avm_access_' + suffix,
    refresh_token: 'avm_refresh_' + suffix,
    scope,
    refresh_request_id: null,
    session_id: 'e757d046-7b23-46f9-87a0-c39075b06cb7',
    expires_in: 300,
  };
}
export function authenticated(scope = READ_SCOPE) {
  const store = new MemoryStore();
  store.state = { tokens: tokens(scope), accessDeadline: Date.now() + 300_000 };
  return store;
}
export function reply(value: unknown, status = 200) {
  return Response.json(value, { status });
}
