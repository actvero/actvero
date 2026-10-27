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
  if (!!ctx.options.file === !!ctx.options.dir) throw new CliError('invalid_argument', '请指定 --file 或 --dir 其中一项');
  const manifestPath = await realpath(ctx.options.dir ? resolve(String(ctx.options.dir), 'client-release.json') : String(ctx.options.file));
  const manifest = await json(manifestPath);
  if (manifest.schema_version !== 1 || !Array.isArray(manifest.artifacts) || manifest.artifacts.length < 1 || manifest.artifacts.length > 10)
    throw new CliError('invalid_manifest', '需要 schema_version=1 的发布清单，最多包含 10 个文件');
  const directory = dirname(manifestPath);
  const feedRoots = object(manifest.feed_roots);
  if (typeof manifest.source_commit !== 'string' || !/^[0-9a-f]{40}$/.test(manifest.source_commit))
    throw new CliError('invalid_manifest', '发布清单需要完整 source_commit，请用新版桌面导出命令重新生成');
  const seen = new Set<string>();
  // Validate and hash the entire input before making the first server mutation.
  const files = [];
  for (const raw of manifest.artifacts) {
    const item = object(raw);
    const kind = String(item.target) + '/' + String(item.role);
    if (seen.has(kind) || !['win-x64','win-arm64','mac-arm64','mac-x64'].includes(String(item.target)) || !['payload','installer','blockmap'].includes(String(item.role)))
      throw new CliError('invalid_manifest', '发布清单包含重复文件或不支持的目标用途');
    seen.add(kind);
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
  for (const target of new Set(files.map(({item}) => String(item.target)))) {
    const required = target.startsWith('win-') ? ['payload', 'blockmap'] : ['payload', 'blockmap', 'installer'];
    if (required.some(role => !seen.has(target + '/' + role))) throw new CliError('incomplete_manifest', '每个目标须包含完整更新文件，Mac 还需要 DMG 安装包');
  }
  if (files.some(({item}) => item.target === 'win-arm64')) await ctx.client.requireCapability('client_distribution.win_arm64');
  let ident = ctx.options.release ? uuid(String(ctx.options.release)) : stableId(ctx.client.server + '/release/' + String(manifest.version));
  if (!ctx.options.release) {
    const listed = await ctx.client.request('GET', BASE + '/releases?version=' + encodeURIComponent(String(manifest.version)));
    const matches = Array.isArray(listed.items) ? listed.items.map(object).filter(r => r.version === manifest.version) : [];
    if (matches.length > 1) throw new CliError('release_conflict', '版本记录不唯一，请维护人员核对');
    if (matches[0]) ident = uuid(String(matches[0].id));
  }
  const override = ctx.options.storage ? uuid(String(ctx.options.storage)) : undefined;
  if (!override) {
    const profiles = await ctx.client.request('GET', '/platform/object-storage');
    if (!Array.isArray(profiles.items) || !profiles.items.some(raw => { const p = object(raw); return p.is_default && p.enabled; }))
      throw new CliError('storage_required', '请在平台设置中配置默认对象存储');
  }
  // Only revision conflicts are retried. Re-read and compare the build identity each time.
  await retryRevision(async () => {
    let existing: Record<string, unknown> | undefined;
    try { existing = await ctx.client.request('GET', BASE + '/releases/' + ident); }
    catch (error) { if (!(error instanceof CliError) || error.status !== 404) throw error; }
    if (existing && (existing.version !== manifest.version || existing.channel !== (manifest.channel || 'latest')))
      throw new CliError('release_mismatch', '目标版本与发布清单不一致');
    if (existing && !existing.source_commit && Array.isArray(existing.artifacts) && existing.artifacts.length)
      throw new CliError('source_required', '该草稿已有未记录源码提交的文件，请使用新版本导入构建清单');
    if (existing?.source_commit && existing.source_commit !== manifest.source_commit)
      throw new CliError('source_mismatch', '该版本已绑定另一份源码提交，不能混用构建产物');
    if (existing?.notes && manifest.notes && existing.notes !== manifest.notes)
      throw new CliError('release_mismatch', '该版本已有不同的更新说明，请先核对版本资料');
    const minimumOS = object(existing?.minimum_os || {});
    for (const [target, value] of Object.entries(object(manifest.minimum_os || {}))) {
      if (minimumOS[target] && minimumOS[target] !== value) throw new CliError('release_mismatch', '同一目标的最低系统版本不同');
    }
    if (!existing || existing.status === 'draft') {
      await ctx.client.request('PUT', BASE + '/releases/' + ident, {
        expected_revision: existing?.revision || 0, version: manifest.version, channel: manifest.channel || 'latest',
        source_commit: manifest.source_commit || null,
        notes: existing?.notes || manifest.notes || '', minimum_os: { ...minimumOS, ...object(manifest.minimum_os || {}) },
      });
    }
  });
  progress(`版本编号：${ident}\n`);
  for (const { item, path, computed } of files) {
    const artifactId = stableId(ident + '/' + String(item.target) + '/' + String(item.role) + '/' + computed.sha512);
    await retryRevision(async () => {
    const row = await ctx.client.request('GET', BASE + '/releases/' + ident);
    await ctx.client.request('PUT', BASE + '/releases/' + ident + '/artifacts/' + artifactId, {
      expected_revision: row.revision, target: item.target, role: item.role,
      filename: item.filename || item.file?.toString().split('/').pop(),
      ...(override ? { storage_id: override } : {}), ...computed,
    });
    });
    await upload(ctx, artifactId, path, progress);
  }
  return ctx.options.wait === false ? ctx.client.request('GET', BASE + '/releases/' + ident) : waitRelease(ctx, ident, files.map(({item}) => String(item.target)), progress);
}

async function retryRevision<T>(run: () => Promise<T>): Promise<T> {
  for (let n = 0; ; n++) {
    try { return await run(); }
    catch (error) {
      if (!(error instanceof CliError) || error.status !== 409 || error.code !== 'revision_conflict' || n >= 3) throw error;
    }
  }
}

export async function waitRelease(ctx: Context, id: string, selected: string[], progress: (text: string) => void): Promise<Record<string, unknown>> {
  const seconds = Number(ctx.options.timeout ?? 900);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 7200) throw new CliError('invalid_argument', '--timeout 须为 1 到 7200 秒');
  const deadline = Date.now() + seconds * 1000;
  while (true) {
    const row = await ctx.client.request('GET', BASE + '/releases/' + uuid(id));
    const artifacts = (Array.isArray(row.artifacts) ? row.artifacts : []).map(object).filter(a => !selected.length || selected.includes(String(a.target)));
    if (!artifacts.length) throw new CliError('release_empty', '该版本尚无待校验文件，请先导入构建清单');
    const failed = artifacts.filter(a => a.status === 'failed');
    if (failed.length) throw new CliError('verification_failed', '文件校验失败：' + failed.map(a => String(a.id)).join(',') + '；使用 releases show/jobs 查看原因，修复后 retry');
    if (artifacts.length && artifacts.every(a => a.status === 'ready')) return row;
    if (Date.now() >= deadline) throw new CliError('verification_timeout', '校验仍在进行；使用 releases wait ' + id + ' 继续等待');
    progress(`等待版本 ${row.version} 校验完成…\n`);
    await new Promise(resolve => setTimeout(resolve, Math.min(2000, deadline - Date.now())));
  }
}

export function registerDistribution(program: Command, run: Run, progress: (text: string) => void): void {
  const scoped = (name: string, description: string) => program.command(name).description(description).option('--target <target>', '平台凭据用途', 'platform');
  const request = async (ctx: Context, method: string, suffix: string, body?: unknown) => {
    await ctx.client.requireCapability('client_distribution.' + (method === 'GET' ? 'read' : 'write'));
    return ctx.client.request(method, BASE + suffix, body);
  };
  const storage = scoped('storage', '平台共享对象存储管理');
  const storageRequest = async (ctx: Context, method: string, suffix = '', body?: unknown) => {
    await ctx.client.requireCapability('object_storage.' + (method === 'GET' ? 'read' : 'write'));
    return ctx.client.request(method, '/platform/object-storage' + suffix, body);
  };
  run(storage.command('list'), ctx => storageRequest(ctx, 'GET'));
  run(storage.command('save <id>').requiredOption('--file <json>', '存储配置 JSON；密钥不回显'), async (ctx, [id]) =>
    storageRequest(ctx, 'PUT', '/' + uuid(id!), await json(String(ctx.options.file))));
  run(storage.command('test <id>'), (ctx, [id]) => storageRequest(ctx, 'POST', '/' + uuid(id!) + '/test'));
  const releases = scoped('releases', '平台客户端发布、上传和更新通道');
  run(releases.command('list'), ctx => request(ctx, 'GET', '/releases'));
  run(releases.command('show <id>'), (ctx, [id]) => request(ctx, 'GET', '/releases/' + uuid(id!)));
  run(releases.command('save <id>').requiredOption('--file <json>', '版本资料 JSON'), async (ctx, [id]) => request(ctx, 'PUT', '/releases/' + uuid(id!), await json(String(ctx.options.file))));
  run(releases.command('import').option('--file <json>', '构建导出的 client-release.json').option('--dir <directory>', '含 client-release.json 的产物目录').option('--storage <uuid>', '覆盖默认对象存储').option('--no-wait', '上传后返回，稍后单独等待校验').option('--timeout <seconds>', '校验等待时间', '900').option('--release <uuid>', '使用已有草稿；默认按平台和版本生成稳定编号'), async ctx => {
    await ctx.client.requireCapability('client_distribution.write');
    await ctx.client.requireCapability('client_distribution.import_manifest');
    return importRelease(ctx, progress);
  });
  run(releases.command('wait <id>').option('--timeout <seconds>', '校验等待时间', '900'), async (ctx, [id]) => {
    await ctx.client.requireCapability('client_distribution.read');
    return waitRelease(ctx, uuid(id!), [], progress);
  });
  run(releases.command('retry <id>'), async (ctx, [id]) => {
    const row = await request(ctx, 'GET', '/releases/' + uuid(id!));
    if (row.status !== 'draft') throw new CliError('release_state', '只能重试草稿中的失败文件');
    const artifacts = (Array.isArray(row.artifacts) ? row.artifacts : []).map(object);
    for (const a of artifacts.filter(a => a.status === 'failed')) await request(ctx, 'POST', '/artifacts/' + uuid(String(a.id)) + '/verify');
    return request(ctx, 'GET', '/releases/' + uuid(id!));
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
  run(releases.command('plan <id>').requiredOption('--revision <n>', '版本修订号').requiredOption('--targets <targets>', '逗号分隔 win-x64,win-arm64,mac-arm64,mac-x64'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/plan', { expected_revision: Number(ctx.options.revision), targets: String(ctx.options.targets).split(',') }));
  run(releases.command('publish <id>').requiredOption('--plan <uuid>', '已检查的发布计划编号；重复使用可回查'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/publish', { plan_id: uuid(String(ctx.options.plan)) }));
  run(releases.command('withdraw <id>').requiredOption('--revision <n>', '版本修订号'), (ctx, [id]) => request(ctx, 'POST', '/releases/' + uuid(id!) + '/withdraw', { expected_revision: Number(ctx.options.revision) }));
}
