import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { open, readFile, realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import type { Command } from 'commander';
import type { Context } from './commands.js';
import { CliError, object, uuid } from './errors.js';

const BASE = '/platform/client-distribution';
type Run = (command: Command, handler: (ctx: Context, args: string[]) => Promise<unknown>) => Command;

async function json(path: string): Promise<Record<string, unknown>> {
  if ((await stat(path)).size > 5_000_000) throw new CliError('invalid_file', '发布清单不得超过 5 MB');
  return object(JSON.parse(await readFile(path, 'utf8')));
}

function stableId(value: string): string {
  const bytes = createHash('sha256').update(value).digest().subarray(0, 16);
  bytes[6] = (bytes[6]! & 15) | 80;
  bytes[8] = (bytes[8]! & 63) | 128;
  const s = bytes.toString('hex');
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

export async function fingerprint(path: string): Promise<{ size_bytes: number; sha512: string }> {
  const info = await stat(path);
  if (!info.isFile() || info.size <= 0 || info.size > 20_000_000_000)
    throw new CliError('invalid_artifact', '发布文件须为 1 字节到 20 GB 的普通文件');
  const hash = createHash('sha512');
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return { size_bytes: info.size, sha512: hash.digest('base64') };
}

export async function upload(ctx: Context, id: string, path: string, progress: (text: string) => void): Promise<unknown> {
  const root = BASE + '/uploads/' + uuid(id);
  const session = await ctx.client.request('POST', root + '/start');
  if (session.status === 'completed') return session;
  if (session.status === 'completing') return ctx.client.request('POST', root + '/complete');
  if (session.status !== 'uploading') throw new CliError('upload_state', '上传状态未就绪，请查询上传任务');
  const computed = await fingerprint(path);
  if (computed.size_bytes !== session.size_bytes || (session.expected_sha512 && computed.sha512 !== session.expected_sha512))
    throw new CliError('file_changed', '文件与上传任务的摘要或大小不一致，不能续传');
  const partSize = Number(session.part_size);
  const count = Number(session.part_count);
  if (!Number.isSafeInteger(partSize) || partSize < 1 || partSize > 64 * 1024 * 1024 || !Number.isInteger(count) || count < 1 || count > 10000)
    throw new CliError('invalid_response', '平台返回了无效的上传分片参数');
  const parts = object(session.parts);
  // Without a declared digest, a reselected file cannot safely reuse remote parts.
  if (!session.expected_sha512) for (const key of Object.keys(parts)) delete parts[key];
  const handle = await open(path, 'r');
  try {
    const size = (await handle.stat()).size;
    if (Math.ceil(size / partSize) !== count) throw new CliError('file_changed', '文件大小与上传任务不一致');
    for (let n = 1; n <= count; n++) {
      if (parts[String(n)]) continue;
      const length = Math.min(partSize, size - (n - 1) * partSize);
      const bytes = Buffer.alloc(length);
      let offset = 0;
      while (offset < length) {
        const read = await handle.read(bytes, offset, length - offset, (n - 1) * partSize + offset);
        if (!read.bytesRead) throw new CliError('file_changed', '文件在上传期间发生变化，请停止并检查');
        offset += read.bytesRead;
      }
      const signed = await ctx.client.request('POST', root + '/sign', { parts: [n] });
      const url = new URL(String(signed[String(n)]));
      if (url.protocol !== 'https:' || url.username || url.password)
        throw new CliError('invalid_response', '上传地址不符合 HTTPS 要求');
      let response: Response;
      try {
        response = await fetch(url, { method: 'PUT', body: bytes, redirect: 'error',
          headers: { 'Content-Length': String(length) }, signal: AbortSignal.timeout(180_000) });
      } catch {
        throw new CliError('upload_interrupted', '分片上传未确认；用相同发布清单重试可继续上传');
      }
      const etag = response.headers.get('etag');
      await response.body?.cancel();
      if (!response.ok || !etag) throw new CliError('upload_failed', '存储未确认分片或缺少 ETag；检查存储配置后恢复');
      await ctx.client.request('POST', root + '/ack', { number: n, etag });
      progress(`上传 ${id}：${n}/${count}\n`);
    }
  } finally { await handle.close(); }
  return ctx.client.request('POST', root + '/complete');
}

export async function importRelease(ctx: Context, progress: (text: string) => void): Promise<unknown> {
  const manifestPath = await realpath(String(ctx.options.file));
  const manifest = await json(manifestPath);
  if (manifest.schema_version !== 1 || !Array.isArray(manifest.artifacts) || manifest.artifacts.length > 9)
    throw new CliError('invalid_manifest', '需要 schema_version=1 的发布清单，最多包含 9 个文件');
  const directory = dirname(manifestPath);
  const feedRoots = object(manifest.feed_roots);
  // Validate and hash the entire input before making the first server mutation.
  const files = [];
  for (const raw of manifest.artifacts) {
    const item = object(raw);
    if (feedRoots[String(item.target)] !== ctx.client.server + '/api/v1/client-updates/actvero/' + String(item.target) + '/')
      throw new CliError('feed_mismatch', '安装包的更新源与目标平台不一致，请使用该平台更新源重新构建');
    if (typeof item.file !== 'string' || isAbsolute(item.file)) throw new CliError('invalid_manifest', '发布文件必须使用清单目录内的相对路径');
    const path = await realpath(resolve(directory, item.file));
    if (relative(directory, path).startsWith('..') || isAbsolute(relative(directory, path)))
      throw new CliError('invalid_manifest', '发布文件不能位于清单目录之外');
    const computed = await fingerprint(path);
    if ((item.sha512 && item.sha512 !== computed.sha512) || (item.size_bytes && item.size_bytes !== computed.size_bytes))
      throw new CliError('checksum_mismatch', '发布文件与清单摘要或大小不匹配');
    files.push({ item, path, computed });
  }
  const ident = ctx.options.release ? uuid(String(ctx.options.release)) : stableId(ctx.client.server + '/release/' + String(manifest.version));
  let existing: Record<string, unknown> | undefined;
  try { existing = await ctx.client.request('GET', BASE + '/releases/' + ident); }
  catch (error) { if (!(error instanceof CliError) || error.status !== 404) throw error; }
  if (existing && (existing.version !== manifest.version || existing.channel !== (manifest.channel || 'latest')))
    throw new CliError('release_mismatch', '目标版本与发布清单不一致');
  if (!existing || existing.status === 'draft') {
    await ctx.client.request('PUT', BASE + '/releases/' + ident, {
      expected_revision: existing?.revision || 0, version: manifest.version, channel: manifest.channel || 'latest',
      notes: manifest.notes || existing?.notes || '', minimum_os: { ...object(existing?.minimum_os || {}), ...object(manifest.minimum_os || {}) },
    });
  }
  progress(`版本编号：${ident}\n`);
  for (const { item, path, computed } of files) {
    const row = await ctx.client.request('GET', BASE + '/releases/' + ident);
    const artifactId = stableId(ident + '/' + String(item.target) + '/' + String(item.role) + '/' + computed.sha512);
    await ctx.client.request('PUT', BASE + '/releases/' + ident + '/artifacts/' + artifactId, {
      expected_revision: row.revision, target: item.target, role: item.role,
      filename: item.filename || item.file?.toString().split('/').pop(),
      storage_id: uuid(String(ctx.options.storage)), ...computed,
    });
    await upload(ctx, artifactId, path, progress);
  }
  return ctx.client.request('GET', BASE + '/releases/' + ident);
}

export function registerDistribution(program: Command, run: Run, progress: (text: string) => void): void {
  const scoped = (name: string, description: string) => program.command(name).description(description).option('--target <target>', '平台凭据用途', 'platform');
  const request = async (ctx: Context, method: string, suffix: string, body?: unknown) => {
    await ctx.client.requireCapability('client_distribution.' + (method === 'GET' ? 'read' : 'write'));
    return ctx.client.request(method, BASE + suffix, body);
  };
  const storage = scoped('storage', '平台客户端对象存储管理');
  run(storage.command('list'), ctx => request(ctx, 'GET', '/storage'));
  run(storage.command('save <id>').requiredOption('--file <json>', '存储配置 JSON；密钥不回显'), async (ctx, [id]) =>
    request(ctx, 'PUT', '/storage/' + uuid(id!), await json(String(ctx.options.file))));
  run(storage.command('test <id>'), (ctx, [id]) => request(ctx, 'POST', '/storage/' + uuid(id!) + '/test'));
  const releases = scoped('releases', '平台客户端发布、上传和更新通道');
  run(releases.command('list'), ctx => request(ctx, 'GET', '/releases'));
  run(releases.command('show <id>'), (ctx, [id]) => request(ctx, 'GET', '/releases/' + uuid(id!)));
  run(releases.command('save <id>').requiredOption('--file <json>', '版本资料 JSON'), async (ctx, [id]) => request(ctx, 'PUT', '/releases/' + uuid(id!), await json(String(ctx.options.file))));
  run(releases.command('import').requiredOption('--file <json>', '构建导出的 client-release.json').requiredOption('--storage <uuid>', '对象存储编号').option('--release <uuid>', '使用已有草稿；默认按平台和版本生成稳定编号'), async ctx => {
    await ctx.client.requireCapability('client_distribution.write');
    return importRelease(ctx, progress);
  });
  run(releases.command('artifact-add <release> <artifact>').requiredOption('--file <json>', '文件或外链描述；含 expected_revision'), async (ctx, [release, artifact]) => request(ctx, 'PUT', '/releases/' + uuid(release!) + '/artifacts/' + uuid(artifact!), await json(String(ctx.options.file))));
  run(releases.command('artifact-remove <id>').requiredOption('--revision <n>', '版本修订号'), (ctx, [id]) => request(ctx, 'DELETE', '/artifacts/' + uuid(id!), { expected_revision: Number(ctx.options.revision) }));
  run(releases.command('verify <artifact>'), (ctx, [id]) => request(ctx, 'POST', '/artifacts/' + uuid(id!) + '/verify'));
  run(releases.command('jobs').option('--artifact <uuid>', '筛选文件'), ctx => request(ctx, 'GET', '/jobs' + (ctx.options.artifact ? '?artifact_id=' + uuid(String(ctx.options.artifact)) : '')));
  run(releases.command('upload <artifact> <file>'), async (ctx, [id, file]) => {
    await ctx.client.requireCapability('client_distribution.write');
    return upload(ctx, uuid(id!), file!, progress);
  });
  run(releases.command('upload-status <id>'), (ctx, [id]) => request(ctx, 'GET', '/uploads/' + uuid(id!)));
  run(releases.command('upload-abort <id>'), (ctx, [id]) => request(ctx, 'POST', '/uploads/' + uuid(id!) + '/abort'));
  run(releases.command('heads'), ctx => request(ctx, 'GET', '/heads'));
  run(releases.command('plan <id>').requiredOption('--revision <n>', '版本修订号').requiredOption('--targets <targets>', '逗号分隔 win-x64,mac-arm64,mac-x64'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/plan', { expected_revision: Number(ctx.options.revision), targets: String(ctx.options.targets).split(',') }));
  run(releases.command('publish <id>').requiredOption('--plan <uuid>', '已检查的发布计划编号；重复使用可回查'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/publish', { plan_id: uuid(String(ctx.options.plan)) }));
  run(releases.command('withdraw <id>').requiredOption('--revision <n>', '版本修订号'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/withdraw', { expected_revision: Number(ctx.options.revision) }));
}
