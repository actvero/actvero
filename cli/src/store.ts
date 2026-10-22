import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { lock } from 'proper-lockfile';
import { configHome, serverKey } from './config.js';
import { CliError, object } from './errors.js';

export interface Tokens {
  access_token: string;
  refresh_token: string;
  scope: string;
  session_id: string;
  expires_in: number;
  refresh_request_id?: string | null;
}
export interface LoginProof {
  attempt_id: string;
  state: string;
  code_verifier: string;
}
export interface SessionState {
  tokens?: Tokens;
  instanceId?: string;
  accessDeadline?: number;
  pending?: { refresh_token: string; request_id: string };
  ack?: string;
  logoutPending?: boolean;
  loginPending?: LoginProof;
}
export interface Store {
  load(): Promise<SessionState>;
  save(value: SessionState): Promise<void>;
  clear(): Promise<void>;
  locked<T>(action: () => Promise<T>): Promise<T>;
}

export class CredentialStore implements Store {
  constructor(private readonly server: string) {}
  private async entry() {
    try {
      const { AsyncEntry } = await import('@napi-rs/keyring');
      // A separate service prevents overwriting the legacy Python client's journal.
      return new AsyncEntry('actvero-cli-node-v1', serverKey(this.server), {
        linux: { store: 'secret-service' },
      });
    } catch {
      throw new CliError(
        'secure_store_unavailable',
        '系统凭据库不可用；需要钥匙串、Windows 凭据库或 Secret Service',
      );
    }
  }
  async load(): Promise<SessionState> {
    try {
      const raw = await (await this.entry()).getPassword();
      return raw ? (object(JSON.parse(raw)) as SessionState) : {};
    } catch {
      throw new CliError('secure_store_unavailable', '无法读取系统凭据库；未发送业务请求');
    }
  }
  async save(value: SessionState): Promise<void> {
    try {
      const entry = await this.entry();
      const raw = JSON.stringify(value);
      await entry.setPassword(raw);
      if ((await entry.getPassword()) !== raw) throw new Error();
    } catch {
      throw new CliError('secure_store_unavailable', '登录凭据未确认保存；不会使用明文替代');
    }
  }
  async clear(): Promise<void> {
    try {
      await (await this.entry()).deleteCredential();
    } catch {
      throw new CliError('secure_store_unavailable', '无法清除系统凭据');
    }
  }
  async locked<T>(action: () => Promise<T>): Promise<T> {
    const directory = join(configHome(), 'locks');
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const target = join(directory, serverKey(this.server));
    await writeFile(target, '', { flag: 'a', mode: 0o600 });
    let release: () => Promise<void>;
    try {
      release = await lock(target, {
        stale: 120_000,
        update: 10_000,
        retries: { retries: 20, factor: 1, minTimeout: 500, maxTimeout: 500 },
      });
    } catch {
      throw new CliError('session_busy', '另一条命令正在使用此平台登录，请稍后重试');
    }
    try {
      return await action();
    } finally {
      await release();
    }
  }
}
