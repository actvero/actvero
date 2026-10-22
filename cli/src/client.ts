import { createHash, randomUUID } from 'node:crypto';
import { CliError, object } from './errors.js';
import type { SessionState, Store, Tokens } from './store.js';

export type Fetch = typeof globalThis.fetch;
export const READ_SCOPE = 'management:read';
export const WRITE_SCOPE = 'management:read management:write';

export function validateTokens(value: unknown): Tokens {
  const data = object(value);
  if (
    ![READ_SCOPE, WRITE_SCOPE].includes(String(data.scope)) ||
    typeof data.access_token !== 'string' ||
    !data.access_token.startsWith('avm_access_') ||
    typeof data.refresh_token !== 'string' ||
    !data.refresh_token.startsWith('avm_refresh_') ||
    typeof data.session_id !== 'string' ||
    !Number.isInteger(data.expires_in) ||
    Number(data.expires_in) < 0 ||
    (data.refresh_request_id != null && typeof data.refresh_request_id !== 'string')
  ) {
    throw new CliError('invalid_response', '平台返回了不兼容的管理凭据');
  }
  return data as unknown as Tokens;
}

export class Client {
  constructor(
    public readonly server: string,
    public readonly store: Store,
    private readonly fetcher: Fetch = globalThis.fetch,
  ) {}

  private async rawRequest(
    method: string,
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(this.server + '/api/v1/management' + path, {
        method,
        redirect: 'manual',
        signal: AbortSignal.timeout(120_000),
        headers: {
          ...(body instanceof Uint8Array
            ? { 'Content-Type': 'application/zip' }
            : body === undefined
              ? {}
              : { 'Content-Type': 'application/json' }),
          ...headers,
        },
        body:
          body instanceof Uint8Array
            ? Buffer.from(body)
            : body === undefined
              ? undefined
              : JSON.stringify(body),
      });
    } catch {
      throw new CliError(
        'network_unavailable',
        '无法确认平台响应；写操作请查询原请求回执，勿重复提交',
      );
    }
    return response;
  }

  async publicRequest(
    method: string,
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<Record<string, unknown>> {
    const response = await this.rawRequest(method, path, body, headers);
    let result: Record<string, unknown>;
    try {
      result = object(await response.json());
    } catch {
      throw new CliError('invalid_response', '平台未返回有效 JSON', response.status);
    }
    if (!response.ok) {
      const error =
        result.error && typeof result.error === 'object'
          ? (result.error as Record<string, unknown>)
          : {};
      throw new CliError(
        typeof error.code === 'string' ? error.code : 'request_failed',
        typeof error.message === 'string' ? error.message : '平台拒绝此请求',
        response.status,
        typeof error.request_id === 'string' ? error.request_id : undefined,
      );
    }
    return result;
  }

  async requireCapability(capability: string): Promise<void> {
    const metadata = await this.publicRequest('GET', '/metadata');
    if (
      metadata.resource_contract_version !== 1 ||
      !Array.isArray(metadata.capabilities) ||
      !metadata.capabilities.includes(capability)
    ) {
      throw new CliError(
        'unsupported_capability',
        '此平台尚未提供所需管理能力，请先升级平台管理接口',
      );
    }
  }

  async saveLogin(tokens: Tokens, instanceId: string, retirePending: string[] = []): Promise<void> {
    await this.store.save({
      tokens,
      instanceId,
      accessDeadline: Date.now() + tokens.expires_in * 1000,
      ...(retirePending.length ? { retirePending } : {}),
    });
  }

  async retireSessions(state: SessionState): Promise<boolean> {
    for (const token of [...(state.retirePending || [])]) {
      try {
        await this.publicRequest('POST', '/logout', { refresh_token: token });
      } catch (error) {
        if (!(error instanceof CliError) || error.code !== 'invalid_credential') return false;
      }
      state.retirePending = state.retirePending!.filter((value) => value !== token);
      if (!state.retirePending.length) delete state.retirePending;
      await this.store.save(state);
    }
    return true;
  }

  private async acknowledge(state: SessionState): Promise<void> {
    if (!state.ack || !state.tokens) return;
    await this.publicRequest('POST', '/refresh/acknowledge', {
      refresh_token: state.tokens.refresh_token,
      request_id: state.ack,
    });
    delete state.ack;
    await this.store.save(state);
  }

  private async refresh(state: SessionState, recovery = true): Promise<SessionState> {
    if (!state.tokens) throw new CliError('login_required', '请先执行 auth login');
    if (!state.pending) {
      state.pending = { refresh_token: state.tokens.refresh_token, request_id: randomUUID() };
      await this.store.save(state);
    }
    const tokens = validateTokens(
      await this.publicRequest('POST', '/refresh', { ...state.pending, recovery_version: 2 }),
    );
    if (tokens.scope !== state.tokens.scope || tokens.session_id !== state.tokens.session_id) {
      throw new CliError('invalid_response', '续期改变了登录权限或会话，请重新登录');
    }
    state.tokens = tokens;
    state.accessDeadline = Date.now() + tokens.expires_in * 1000;
    delete state.pending;
    state.ack = tokens.refresh_request_id || undefined;
    await this.store.save(state);
    await this.acknowledge(state);
    if (state.accessDeadline <= Date.now() + 10_000) {
      if (!recovery) throw new CliError('invalid_response', '平台连续返回过期凭据，请重新登录');
      return this.refresh(state, false);
    }
    return state;
  }

  private async tokens(force = false): Promise<Tokens> {
    let state = await this.store.load();
    await this.retireSessions(state);
    if (!state.tokens) throw new CliError('login_required', '请先执行 auth login');
    validateTokens(state.tokens);
    if (state.logoutPending)
      throw new CliError('logout_pending', '上次退出未确认，请先重试 auth logout');
    if (
      force ||
      state.pending ||
      !state.accessDeadline ||
      state.accessDeadline <= Date.now() + 10_000
    )
      state = await this.refresh(state);
    else await this.acknowledge(state);
    return state.tokens!;
  }

  async request(
    method: string,
    path: string,
    body?: unknown,
    requestId?: string,
  ): Promise<Record<string, unknown>> {
    return this.store.locked(async () => {
      let tokens = await this.tokens();
      if (requestId && tokens.scope !== WRITE_SCOPE)
        throw new CliError(
          'insufficient_scope',
          '当前登录只读；运行 auth login，在浏览器重新授权管理权限',
        );
      const send = () =>
        this.publicRequest(method, path, body, {
          Authorization: 'Bearer ' + tokens.access_token,
          ...(requestId ? { 'X-Management-Request-ID': requestId } : {}),
        });
      try {
        return await send();
      } catch (error) {
        // GET can be retried once after an explicit expiry. Never replay a mutation here.
        if (!(error instanceof CliError) || error.code !== 'access_expired' || method !== 'GET')
          throw error;
        tokens = await this.tokens(true);
        return send();
      }
    });
  }

  async download(
    path: string,
    orgId: string,
    requestId: string,
  ): Promise<{ bytes: Buffer; sha256: string }> {
    return this.store.locked(async () => {
      const tokens = await this.tokens();
      if (tokens.scope !== WRITE_SCOPE)
        throw new CliError('insufficient_scope', '下载会记录分发，请运行 auth login 并在浏览器授权管理权限');
      const response = await this.rawRequest('POST', path, undefined, {
        Authorization: 'Bearer ' + tokens.access_token,
        'X-Management-Request-ID': requestId,
      });
      if (!response.ok) {
        let error: Record<string, unknown> = {};
        try {
          error = object(object(await response.json()).error);
        } catch {
          /* no raw body */
        }
        throw new CliError(
          typeof error.code === 'string' ? error.code : 'download_failed',
          typeof error.message === 'string' ? error.message : '下载未确认，请查询原请求回执',
          response.status,
        );
      }
      const expected = response.headers.get('X-Content-SHA256') || '';
      if (
        response.headers.get('Content-Type')?.split(';')[0] !== 'application/zip' ||
        response.headers.get('X-Organization-ID') !== orgId ||
        response.headers.get('X-Management-Request-ID') !== requestId ||
        !/^[a-f0-9]{64}$/.test(expected) ||
        !response.body
      ) {
        await response.body?.cancel();
        throw new CliError('invalid_download', '下载的组织、请求编号或校验信息不匹配');
      }
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 20 * 1024 * 1024)
            throw new CliError('package_too_large', '下载超过 20 MB 限制');
          chunks.push(value);
        }
      } catch (error) {
        await reader.cancel().catch(() => {});
        if (error instanceof CliError) throw error;
        throw new CliError('download_interrupted', '下载中断，请使用原请求编号恢复');
      } finally {
        reader.releaseLock();
      }
      const bytes = Buffer.concat(chunks);
      const sha256 = createHash('sha256').update(bytes).digest('hex');
      if (sha256 !== expected)
        throw new CliError('checksum_mismatch', '技能包 SHA-256 校验失败');
      return { bytes, sha256 };
    });
  }

  async logout(): Promise<void> {
    await this.store.locked(async () => {
      const state = await this.store.load();
      if (!(await this.retireSessions(state)))
        throw new CliError('logout_pending', '旧会话退出尚未确认，请重试 auth logout');
      if (state.loginPending)
        await this.publicRequest('POST', '/login/cancel', state.loginPending);
      if (state.tokens) {
        validateTokens(state.tokens);
        state.logoutPending = true;
        await this.store.save(state);
        await this.publicRequest('POST', '/logout', {
          refresh_token: state.tokens.refresh_token,
        });
      }
      await this.store.clear();
    });
  }
}
