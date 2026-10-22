import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { CliError, object } from './errors.js';

export function normalizeServer(value: string): string {
  try {
    const url = new URL(value);
    if (
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      !['http:', 'https:'].includes(url.protocol) ||
      (url.protocol === 'http:' && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
    )
      throw new Error();
    return url.origin + url.pathname.replace(/\/+$/, '');
  } catch {
    throw new CliError('invalid_server', '平台地址须为 HTTPS；HTTP 仅用于本机回环地址');
  }
}

export function configHome(): string {
  return process.env.ACTVERO_CLI_HOME || join(homedir(), '.config', 'actvero-cli');
}

export function serverKey(server: string): string {
  return createHash('sha256').update(server).digest('hex');
}

export async function atomicJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = path + '.' + randomUUID() + '.tmp';
  await writeFile(temporary, JSON.stringify(value), { flag: 'wx', mode: 0o600 });
  await rename(temporary, path);
}

export async function serverFor(explicit?: string): Promise<string> {
  if (explicit) return normalizeServer(explicit);
  try {
    const saved = object(JSON.parse(await readFile(join(configHome(), 'settings.json'), 'utf8')));
    if (typeof saved.server === 'string') return normalizeServer(saved.server);
  } catch {
    /* Configuration never contains credentials. */
  }
  throw new CliError('server_required', '请用 --server 指定平台地址，或先执行 auth login');
}

export async function saveServer(server: string): Promise<void> {
  await atomicJson(join(configHome(), 'settings.json'), { server });
}

export async function saveCommand(
  server: string,
  org: string,
  requestId: string,
  operation: string,
): Promise<void> {
  await atomicJson(join(configHome(), 'requests', serverKey(server), requestId + '.json'), {
    server,
    org,
    request_id: requestId,
    operation,
    created_at: new Date().toISOString(),
  });
}
