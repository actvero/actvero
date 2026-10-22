import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { hostname } from 'node:os';
import open from 'open';
import { Client, validateTokens } from './client.js';
import { saveServer } from './config.js';
import { CliError } from './errors.js';
import type { LoginProof } from './store.js';

export class Loopback {
  private server: Server;
  private state = '';
  private issuer = '';
  private resolve?: (value: { code: string; issuer: string }) => void;
  private reject?: (reason: Error) => void;
  private timer?: ReturnType<typeof setTimeout>;
  private finished = false;
  redirectUri = '';
  readonly result: Promise<{ code: string; issuer: string }>;

  constructor(timeoutMs = 300_000) {
    this.result = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
    // A browser can fail before anyone starts awaiting the callback.
    void this.result.catch(() => {});
    this.server = createServer((request, response) => {
      let accepted = false;
      try {
        const url = new URL(request.url || '/', this.redirectUri);
        const expected = Buffer.from(this.state);
        const received = Buffer.from(url.searchParams.get('state') || '');
        const single = (name: string) =>
          url.searchParams.getAll(name).length === 1 && !!url.searchParams.get(name);
        if (
          !this.finished &&
          this.state &&
          request.method === 'GET' &&
          request.headers.host === new URL(this.redirectUri).host &&
          url.pathname === '/actvero/cli/callback' &&
          single('state') &&
          single('iss') &&
          received.length === expected.length &&
          timingSafeEqual(received, expected) &&
          url.searchParams.get('iss') === this.issuer
        ) {
          if (single('error') && !url.searchParams.has('code')) {
            this.finished = true;
            this.reject!(new CliError('login_cancelled', '浏览器登录未完成'));
            accepted = true;
          } else if (single('code') && !url.searchParams.has('error')) {
            this.finished = true;
            this.resolve!({ code: url.searchParams.get('code')!, issuer: this.issuer });
            accepted = true;
          }
        }
      } catch {
        /* Reject malformed callbacks without logging query parameters. */
      }
      response.writeHead(accepted ? 200 : 400, {
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'none'",
      });
      response.end(
        accepted ? 'Actvero CLI 已收到登录结果，可以关闭此页面。' : '无效的 CLI 登录回调。',
      );
    });
    this.timer = setTimeout(
      () => this.reject!(new CliError('login_timeout', '等待浏览器登录超时')),
      timeoutMs,
    );
    this.timer.unref();
  }

  async listen(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.server.once('error', reject);
      this.server.listen(0, '127.0.0.1', () => {
        this.server.off('error', reject);
        resolve();
      });
    });
    this.redirectUri = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}/actvero/cli/callback`;
  }
  expect(state: string, issuer: string): void {
    this.state = state;
    this.issuer = issuer;
  }
  async close(): Promise<void> {
    clearTimeout(this.timer);
    this.server.closeAllConnections();
    if (this.server.listening)
      await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }
}

type Browser = (url: string) => Promise<unknown>;

export async function login(
  client: Client,
  write = false,
  reauthenticate = false,
  browser: Browser = open,
): Promise<Record<string, unknown>> {
  return client.store.locked(async () => {
    const previous = await client.store.load();
    if (previous.loginPending) {
      await client.publicRequest('POST', '/login/cancel', previous.loginPending);
      delete previous.loginPending;
      await client.store.save(previous);
    }
    if (previous.logoutPending)
      throw new CliError(
        'logout_pending',
        '上次退出尚未确认，请先重试 auth logout',
      );
    await client.retireSessions(previous);
    await client.store.save(previous);
    const metadata = await client.publicRequest('GET', '/metadata');
    if (
      metadata.contract_version !== 1 ||
      metadata.authorization_contract_version !== 2 ||
      typeof metadata.issuer !== 'string' ||
      typeof metadata.instance_id !== 'string' ||
      !Array.isArray(metadata.supported_scopes)
    ) {
      throw new CliError('unsupported_contract', '平台尚不支持浏览器授权，请先升级平台');
    }
    if (write) process.stderr.write('--write 仅保留兼容；实际组织和权限由本人在浏览器选择。\n');
    const callback = new Loopback();
    let proof: LoginProof | undefined;
    let completed = false;
    try {
      await callback.listen();
      const verifier = randomBytes(36).toString('base64url');
      const started = await client.publicRequest('POST', '/login/start', {
        contract_version: 1,
        authorization_version: 2,
        redirect_uri: callback.redirectUri,
        code_challenge: createHash('sha256').update(verifier).digest('base64url'),
        device_name: 'CLI · ' + hostname().slice(0, 80),
        reauthenticate,
      });
      if (
        typeof started.state !== 'string' ||
        typeof started.attempt_id !== 'string' ||
        typeof started.authorization_url !== 'string'
      ) {
        throw new CliError('invalid_response', '登录请求返回格式不兼容');
      }
      proof = { attempt_id: started.attempt_id, state: started.state, code_verifier: verifier };
      await client.store.save({ ...previous, loginPending: proof });
      const target = new URL(started.authorization_url);
      if (
        started.issuer !== metadata.issuer ||
        target.origin !== new URL(client.server).origin ||
        target.pathname !== new URL(client.server + '/cli/authorize').pathname ||
        target.search !== '' ||
        target.username ||
        target.password ||
        !['https:', 'http:'].includes(target.protocol) ||
        (target.protocol === 'http:' &&
          !['localhost', '127.0.0.1', '[::1]'].includes(target.hostname))
      ) {
        throw new CliError('issuer_mismatch', '授权地址与目标平台不一致');
      }
      callback.expect(started.state, metadata.issuer);
      try {
        await browser(started.authorization_url);
      } catch {
        throw new CliError('browser_unavailable', '无法打开默认浏览器，请在有浏览器的本机登录');
      }
      const returned = await callback.result;
      const tokens = validateTokens(
        await client.publicRequest('POST', '/login/exchange', { ...proof, ...returned }),
      );
      const retirePending = [...(previous.retirePending || [])];
      if (previous.tokens) retirePending.push(previous.tokens.refresh_token);
      await client.saveLogin(tokens, metadata.instance_id, retirePending);
      completed = true;
      const retired = await client.retireSessions(await client.store.load());
      await saveServer(client.server);
      return {
        server: client.server, session_id: tokens.session_id, scope: tokens.scope,
        ...(retired ? {} : { warning: '新授权已保存；旧会话退出尚未确认，下次命令会重试清理' }),
      };
    } finally {
      await callback.close();
      if (proof && !completed) {
        try {
          await client.publicRequest('POST', '/login/cancel', proof);
          await client.store.save(previous);
        } catch {
          /* Preserve the original cancellation proof for the next login. */
        }
      }
    }
  });
}
