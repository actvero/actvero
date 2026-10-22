import { randomUUID } from 'node:crypto';
import { open as openFile, readFile, stat, unlink } from 'node:fs/promises';
import { Command } from 'commander';
import open from 'open';
import { resolve } from 'node:path';
import { Client } from './client.js';
import { saveCommand, serverFor } from './config.js';
import { CliError, object, uuid } from './errors.js';
import { login } from './login.js';
import { CredentialStore } from './store.js';
import {
  example,
  exampleNames,
  guide,
  guideTopics,
  installSkill,
  schema,
  schemaList,
  skillPath,
} from './manual.js';

type Options = Record<string, string | boolean | undefined>;
interface Context {
  client: Client;
  options: Options;
  root: string;
}
export interface Runtime {
  client?: (server: string) => Client;
  output?: (text: string) => void;
  errorOutput?: (text: string) => void;
  journal?: typeof saveCommand;
  openBrowser?: (url: string) => Promise<unknown>;
}

function positive(value: string): string {
  if (!/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(Number(value)))
    throw new CliError('invalid_number', '版本修订号与页码须为正整数');
  return value;
}
async function jsonFile(path: string): Promise<Record<string, unknown>> {
  try {
    if ((await stat(path)).size > 5_000_000) throw new Error();
    return object(JSON.parse(await readFile(path, 'utf8')));
  } catch {
    throw new CliError('invalid_file', '请提供不超过 5 MB 的 JSON 对象文件');
  }
}
async function zipFile(path: string): Promise<Buffer> {
  try {
    if ((await stat(path)).size > 20 * 1024 * 1024) throw new Error();
    return await readFile(path);
  } catch {
    throw new CliError('invalid_package', '无法读取技能 ZIP，文件不得超过 20 MB');
  }
}
function query(options: Options, keys: string[]): string {
  const params = new URLSearchParams();
  for (const key of keys)
    if (typeof options[key] === 'string') params.set(key, options[key] as string);
  return params.size ? '?' + params.toString() : '';
}

export function buildProgram(runtime: Runtime = {}): Command {
  const output = runtime.output || ((text: string) => process.stdout.write(text));
  const errorOutput = runtime.errorOutput || ((text: string) => process.stderr.write(text));
  const journal = runtime.journal || saveCommand;
  const program = new Command()
    .enablePositionalOptions()
    .name('actvero')
    .description('Actvero 多组织资源管理 CLI')
    .version('0.2.0-dev.1');
  program
    .option('--server <url>', '平台地址；默认使用上次成功登录的平台')
    .option('--json', '输出稳定的 JSON 结果');
  program.exitOverride();
  program.configureOutput({ writeErr: () => {} });

  const local = (
    command: Command,
    handler: (args: string[], options: Options) => Promise<unknown>,
  ) => {
    command.option('--json', '输出紧凑 JSON').action(async () => {
      const options = command.optsWithGlobals() as Options;
      const result = await handler(command.processedArgs as string[], options);
      output(JSON.stringify(result, null, options.json ? undefined : 2) + '\n');
    });
  };
  const guides = program.command('guide').description('离线 Agent 操作手册');
  local(guides.command('list'), async () => ({ topics: guideTopics() }));
  local(guides.command('show <topic>'), async ([topic]) => guide(topic!));
  const schemas = program.command('schema').description('离线请求与响应 JSON Schema');
  local(schemas.command('list'), schemaList);
  local(schemas.command('show <name>'), async ([name]) => schema(name!));
  const examples = program.command('example').description('输出可编辑的非机密请求示例');
  local(examples.command('list'), async () => ({ examples: exampleNames() }));
  local(examples.command('show <name>'), async ([name]) => example(name!));
  const agentSkill = program.command('agent-skill').description('查找或安装随包 Agent Skill');
  local(agentSkill.command('path'), async () => ({ path: await skillPath() }));
  local(
    agentSkill
      .command('install')
      .requiredOption('--to <directory>', 'Agent 的 skills 父目录；已有 Skill 不覆盖'),
    async (_args, options) => installSkill(String(options.to)),
  );

  const run = (
    command: Command,
    handler: (context: Context, args: string[]) => Promise<unknown>,
  ) => {
    command.option('--server <url>', '平台地址').option('--json', '输出紧凑 JSON');
    command.action(async (..._args: unknown[]) => {
      const options = command.optsWithGlobals() as Options;
      const server = await serverFor(
        typeof options.server === 'string' ? options.server : undefined,
      );
      const client =
        runtime.client?.(server) || new Client(server, new CredentialStore(server));
      const root = typeof options.org === 'string' ? '/organizations/' + uuid(options.org) : '';
      const result = await handler(
        { client, options, root },
        command.processedArgs as string[],
      );
      output(JSON.stringify(result, null, options.json ? undefined : 2) + '\n');
    });
    return command;
  };
  const scoped = (parent: Command, name: string, description: string) =>
    parent
      .command(name)
      .description(description)
      .requiredOption('--org <uuid>', '目标组织 UUID', uuid);
  const writeOptions = (command: Command) =>
    command.option('--request-id <uuid>', '复用原请求编号以回查或恢复；内容必须一致', uuid);
  const read = async (
    ctx: Context,
    kind: string,
    suffix: string,
    method = 'GET',
    body?: unknown,
  ) => {
    await ctx.client.requireCapability(kind + '.read');
    return ctx.client.request(method, ctx.root + '/' + kind + suffix, body);
  };
  const mutate = async (
    ctx: Context,
    kind: string,
    method: string,
    suffix: string,
    body?: unknown,
  ) => {
    await ctx.client.requireCapability(kind + '.write');
    const id = typeof ctx.options.requestId === 'string' ? ctx.options.requestId : randomUUID();
    const path = ctx.root + '/' + kind + suffix;
    await journal(ctx.client.server, String(ctx.options.org), id, method + ' ' + path);
    errorOutput('请求编号：' + id + '\n');
    return ctx.client.request(method, path, body, id);
  };
  const fromFile = (ctx: Context) => jsonFile(String(ctx.options.file));
  const revision = (ctx: Context) => Number(ctx.options.revision);

  const platform = program.command('platform').description('无需登录查看平台管理能力');
  run(platform.command('info'), (ctx) => ctx.client.publicRequest('GET', '/metadata'));

  const auth = program.command('auth').description('独立 CLI 登录与凭据');
  run(
    auth
      .command('login')
      .option('--write', '明确申请管理写权限')
      .option('--reauthenticate', '重新验证登录'),
    (ctx) => login(ctx.client, !!ctx.options.write, !!ctx.options.reauthenticate),
  );
  run(auth.command('status'), (ctx) => ctx.client.request('GET', '/me'));
  run(auth.command('logout'), async (ctx) => {
    await ctx.client.logout();
    return { server: ctx.client.server, message: '已退出 CLI 登录' };
  });
  const org = program.command('org').description('组织与当前权限');
  run(org.command('list').option('--page <number>', '页码', positive, '1'), (ctx) =>
    ctx.client.request('GET', '/organizations' + query(ctx.options, ['page'])),
  );
  run(scoped(org, 'show', '查看目标组织'), (ctx) => ctx.client.request('GET', ctx.root));
  run(scoped(org, 'permissions', '查看目标组织当前权限'), (ctx) =>
    ctx.client.request('GET', ctx.root + '/permissions'),
  );

  const channels = program.command('channels').description('渠道只读查询');
  run(
    scoped(channels, 'list', '查询渠道')
      .option('--q <text>', '搜索词')
      .option('--page <number>', '页码', positive, '1')
      .option('--state <state>', 'current、archived 或 all'),
    (ctx) =>
      ctx.client.request(
        'GET',
        ctx.root + '/channels' + query(ctx.options, ['q', 'page', 'state']),
      ),
  );
  run(scoped(channels, 'show <id>', '查看渠道详情'), (ctx, [id]) =>
    ctx.client.request('GET', ctx.root + '/channels/' + uuid(id!)),
  );

  const skills = program.command('skills').description('技能包、版本与发布');
  run(
    scoped(skills, 'list', '查询技能')
      .option('--q <text>', '搜索词')
      .option('--category <id>', '类别')
      .option('--status <status>', 'published 或 unpublished')
      .option('--page <number>', '页码', positive, '1'),
    (ctx) => read(ctx, 'skills', query(ctx.options, ['q', 'category', 'status', 'page'])),
  );
  run(scoped(skills, 'show <id>', '查看技能与全部版本'), (ctx, [id]) =>
    read(ctx, 'skills', '/' + uuid(id!)),
  );
  run(scoped(skills, 'preview <zip>', '校验并预览技能 ZIP，不保存'), async (ctx, [path]) =>
    read(ctx, 'skills', '/preview', 'POST', await zipFile(path!)),
  );
  run(
    writeOptions(
      scoped(skills, 'import <zip>', '导入技能或新增版本草稿')
        .requiredOption('--version <version>', '包版本，例如 1.0.0')
        .option('--metadata <file>', '展示资料、分类与使用范围 JSON')
        .option('--skill <uuid>', '新增版本所属技能', uuid)
        .option('--revision <number>', '现有技能修订号', positive),
    ),
    async (ctx, [path]) => {
      if (ctx.options.skill && !ctx.options.revision)
        throw new CliError('revision_required', '导入现有技能的新版本需要 --revision');
      const bytes = await zipFile(path!);
      const preview = object((await read(ctx, 'skills', '/preview', 'POST', bytes)).result);
      const metadata = ctx.options.metadata ? await jsonFile(String(ctx.options.metadata)) : {};
      return mutate(ctx, 'skills', 'POST', '/import', {
        display_name: preview.name,
        description: preview.description,
        audience: 'administrators',
        ...metadata,
        package_base64: bytes.toString('base64'),
        version: ctx.options.version,
        ...(ctx.options.skill ? { skill_id: ctx.options.skill, revision: revision(ctx) } : {}),
      });
    },
  );
  run(
    writeOptions(
      scoped(skills, 'update <id>', '修改资料与范围；文件必须包含 revision').requiredOption(
        '--file <json>',
        'SkillUpdate JSON',
      ),
    ),
    async (ctx, [id]) => mutate(ctx, 'skills', 'PUT', '/' + uuid(id!), await fromFile(ctx)),
  );
  for (const action of ['publish', 'withdraw']) {
    run(
      writeOptions(
        scoped(
          skills,
          action + ' <id>',
          action === 'publish' ? '发布指定版本' : '停止指定版本使用',
        )
          .requiredOption('--version-id <uuid>', '技能版本 UUID', uuid)
          .requiredOption('--revision <number>', '当前技能修订号', positive),
      ),
      ctxAndId(action),
    );
  }
  function ctxAndId(action: string) {
    return (ctx: Context, [id]: string[]) =>
      mutate(ctx, 'skills', 'POST', `/${uuid(id!)}/versions/${ctx.options.versionId}/actions`, {
        action,
        revision: revision(ctx),
      });
  }
  run(
    writeOptions(
      scoped(skills, 'delete-draft <id>', '仅删除从未发布的版本草稿')
        .requiredOption('--version-id <uuid>', '版本 UUID', uuid)
        .requiredOption('--revision <number>', '技能修订号', positive),
    ),
    (ctx, [id]) =>
      mutate(
        ctx,
        'skills',
        'DELETE',
        `/${uuid(id!)}/versions/${ctx.options.versionId}?revision=${revision(ctx)}`,
      ),
  );
  run(
    scoped(skills, 'files <id>', '查看指定版本的文件概览').requiredOption(
      '--version-id <uuid>',
      '版本 UUID',
      uuid,
    ),
    (ctx, [id]) =>
      read(ctx, 'skills', `/${uuid(id!)}/versions/${ctx.options.versionId}/overview`),
  );

  const mcp = program.command('mcp').description('平台 MCP 服务配置、发现与连接');
  run(scoped(mcp, 'list', '查询 MCP 服务'), (ctx) => read(ctx, 'mcp', '/services'));
  run(scoped(mcp, 'show <id>', '查看 MCP 服务配置'), async (ctx, [id]) => {
    const response = await read(ctx, 'mcp', '/services');
    const items = object(response.result).items;
    const value = Array.isArray(items)
      ? items.find((item) => object(item).id === uuid(id!))
      : undefined;
    if (!value) throw new CliError('not_found', '此组织中不存在该 MCP 服务', 404);
    return { ...response, result: value };
  });
  run(
    writeOptions(
      scoped(mcp, 'create', '创建服务，初始关闭').requiredOption(
        '--file <json>',
        'McpServiceWrite JSON',
      ),
    ),
    async (ctx) => mutate(ctx, 'mcp', 'POST', '/services', await fromFile(ctx)),
  );
  run(
    writeOptions(
      scoped(mcp, 'update <id>', '修改服务配置；文件必须包含 version').requiredOption(
        '--file <json>',
        'McpServiceUpdate JSON',
      ),
    ),
    async (ctx, [id]) =>
      mutate(ctx, 'mcp', 'PUT', '/services/' + uuid(id!), await fromFile(ctx)),
  );
  run(
    writeOptions(
      scoped(mcp, 'delete <id>', '删除服务及平台保存的连接数据').requiredOption(
        '--version <number>',
        '当前配置版本',
        positive,
      ),
    ),
    (ctx, [id]) =>
      mutate(
        ctx,
        'mcp',
        'DELETE',
        '/services/' + uuid(id!) + '?version=' + ctx.options.version,
      ),
  );
  run(scoped(mcp, 'capabilities <id>', '查询发现的工具、提示词和资源'), (ctx, [id]) =>
    read(ctx, 'mcp', `/services/${uuid(id!)}/capabilities`),
  );
  run(writeOptions(scoped(mcp, 'discover <id>', '显式连接服务并刷新能力目录')), (ctx, [id]) =>
    mutate(ctx, 'mcp', 'POST', `/services/${uuid(id!)}/discover`),
  );
  for (const [name, suffix] of [
    ['policy', 'policy'],
    ['connect', 'connection'],
    ['presentation', 'presentation'],
  ] as const) {
    run(
      writeOptions(
        scoped(
          mcp,
          name + ' <id>',
          name === 'connect'
            ? '保存本人或组织共享凭据；OAuth 请使用 mcp oauth start'
            : '更新服务设置',
        ).requiredOption('--file <json>', '请求 JSON 文件'),
      ),
      async (ctx, [id]) =>
        mutate(ctx, 'mcp', 'PUT', `/services/${uuid(id!)}/${suffix}`, await fromFile(ctx)),
    );
  }
  run(writeOptions(scoped(mcp, 'disconnect <id>', '断开本人或组织共享连接')), (ctx, [id]) =>
    mutate(ctx, 'mcp', 'DELETE', `/services/${uuid(id!)}/connection`),
  );
  run(
    scoped(mcp, 'preview-import', '预览配置导入').requiredOption(
      '--file <json>',
      'McpImport 或 McpImportRequest JSON',
    ),
    async (ctx) => {
      const input = await fromFile(ctx);
      const body = Object.hasOwn(input, 'configuration') ? input : { configuration: input };
      return read(ctx, 'mcp', '/import/preview', 'POST', body);
    },
  );
  run(
    writeOptions(
      scoped(mcp, 'import', '导入配置，保存不触发发现').requiredOption(
        '--file <json>',
        'McpImport 或 McpImportRequest JSON',
      ),
    ),
    async (ctx) => mutate(ctx, 'mcp', 'POST', '/import', await fromFile(ctx)),
  );
  run(scoped(mcp, 'export', '导出脱敏配置'), (ctx) => read(ctx, 'mcp', '/export'));

  const experts = program.command('experts').description('专家草稿、精确依赖与发布');
  run(
    scoped(experts, 'list', '查询专家')
      .option('--q <text>', '搜索词')
      .option('--category <id>', '类别')
      .option('--status <status>', 'published 或 unpublished')
      .option('--page <number>', '页码', positive, '1'),
    (ctx) => read(ctx, 'experts', query(ctx.options, ['q', 'category', 'status', 'page'])),
  );
  run(scoped(experts, 'show <id>', '查看专家与发布版本'), (ctx, [id]) =>
    read(ctx, 'experts', '/' + uuid(id!)),
  );
  run(scoped(experts, 'check <id>', '检查草稿和依赖的发布资格'), async (ctx, [id]) => {
    const result = await read(ctx, 'experts', '/' + uuid(id!));
    return { ...result, result: object(result.result).check };
  });
  run(
    writeOptions(
      scoped(experts, 'create', '创建专家草稿').requiredOption(
        '--file <json>',
        'ExpertSave JSON',
      ),
    ),
    async (ctx) => mutate(ctx, 'experts', 'POST', '', await fromFile(ctx)),
  );
  for (const [action, method, suffix] of [
    ['update', 'PUT', ''],
    ['scope', 'PUT', '/scope'],
    ['refresh-skills', 'POST', '/refresh-skills'],
  ] as const) {
    run(
      writeOptions(
        scoped(experts, action + ' <id>', '修改专家；文件必须包含 revision').requiredOption(
          '--file <json>',
          '请求 JSON 文件',
        ),
      ),
      async (ctx, [id]) =>
        mutate(ctx, 'experts', method, '/' + uuid(id!) + suffix, await fromFile(ctx)),
    );
  }
  run(
    writeOptions(
      scoped(experts, 'publish <id>', '创建不可变发布版本')
        .requiredOption('--revision <number>', '当前草稿修订号', positive)
        .requiredOption('--version <version>', '发布版本')
        .option('--notes <text>', '发布说明'),
    ),
    (ctx, [id]) =>
      mutate(ctx, 'experts', 'POST', `/${uuid(id!)}/publish`, {
        revision: revision(ctx),
        version: ctx.options.version,
        release_notes: ctx.options.notes || '',
      }),
  );
  for (const action of ['withdraw', 'delete']) {
    run(
      writeOptions(
        scoped(
          experts,
          action + ' <id>',
          action === 'withdraw'
            ? '下架，保留草稿与历史'
            : '删除专家和其发布版本，保留 Skill/MCP',
        ).requiredOption('--revision <number>', '当前修订号', positive),
      ),
      (ctx, [id]) =>
        mutate(
          ctx,
          'experts',
          action === 'delete' ? 'DELETE' : 'POST',
          '/' + uuid(id!) + (action === 'withdraw' ? '/withdraw' : ''),
          { revision: revision(ctx) },
        ),
    );
  }
  run(
    scoped(experts, 'dependencies', '查询可引用的技能版本或 MCP')
      .requiredOption('--kind <kind>', 'skills 或 connectors')
      .option('--q <text>', '搜索词')
      .option('--page <number>', '页码', positive, '1'),
    (ctx) => read(ctx, 'experts', '/dependencies' + query(ctx.options, ['kind', 'q', 'page'])),
  );

  for (const [kind, parent] of [
    ['skills', skills],
    ['experts', experts],
  ] as const) {
    const categories = parent.command('categories').description('分类维护；删除时迁移已有资源');
    const cap = (ctx: Context) => ctx.client.requireCapability(kind + '.categories');
    run(scoped(categories, 'list', '查询分类、资源数量及修订号'), async (ctx) => {
      await cap(ctx);
      return read(ctx, kind, '/categories');
    });
    run(
      writeOptions(
        scoped(categories, 'create', '新增分类').requiredOption('--name <text>', '类别名称'),
      ),
      async (ctx) => {
        await cap(ctx);
        return mutate(ctx, kind, 'POST', '/categories', { name: ctx.options.name });
      },
    );
    for (const action of ['rename', 'move', 'delete']) {
      const command = writeOptions(
        scoped(categories, action + ' <id>', '维护现有分类').requiredOption(
          '--revision <number>',
          '当前修订号',
          positive,
        ),
      );
      if (action === 'rename') command.requiredOption('--name <text>', '新名称');
      if (action === 'move') command.requiredOption('--direction <direction>', 'up 或 down');
      if (action === 'delete')
        command
          .requiredOption('--count <number>', '确认的资源数量', (value) => {
            if (!/^(0|[1-9][0-9]*)$/.test(value) || !Number.isSafeInteger(Number(value)))
              throw new CliError('invalid_number', '数量须为非负整数');
            return value;
          })
          .requiredOption('--target <id>', '资源迁入的分类 ID');
      run(command, async (ctx, [id]) => {
        await cap(ctx);
        if (!/^[a-z0-9-]{1,36}$/.test(id!))
          throw new CliError('invalid_category', '分类 ID 无效');
        return mutate(
          ctx,
          kind,
          action === 'rename' ? 'PATCH' : action === 'delete' ? 'DELETE' : 'POST',
          '/categories/' + id + (action === 'move' ? '/move' : ''),
          {
            revision: revision(ctx),
            ...(action === 'rename'
              ? { name: ctx.options.name }
              : action === 'move'
                ? { direction: ctx.options.direction }
                : { count: Number(ctx.options.count), target_id: ctx.options.target }),
          },
        );
      });
    }
  }
  run(scoped(skills, 'icons', '查询图标目录'), (ctx) => read(ctx, 'skills', '/icon-catalog'));
  run(
    scoped(skills, 'file <id>', '读取指定版本的单个文本文件')
      .requiredOption('--version-id <uuid>', '版本 UUID', uuid)
      .requiredOption('--path <path>', '包内路径'),
    (ctx, [id]) =>
      read(
        ctx,
        'skills',
        `/${uuid(id!)}/versions/${ctx.options.versionId}/file?` +
          new URLSearchParams({ path: String(ctx.options.path) }),
      ),
  );
  run(
    scoped(skills, 'distributions', '查询技能分发记录')
      .option('--skill <uuid>', '技能 UUID', uuid)
      .option('--page <number>', '页码', positive, '1'),
    (ctx) =>
      read(
        ctx,
        'skills',
        '/distributions' +
          query({ skill_id: ctx.options.skill, page: ctx.options.page }, ['skill_id', 'page']),
      ),
  );
  run(
    writeOptions(
      scoped(skills, 'download <id>', '下载技能 ZIP 并核验 SHA-256，记录一次分发')
        .requiredOption('--version-id <uuid>', '版本 UUID', uuid)
        .requiredOption('--out <path>', '新文件路径，不覆盖已有文件'),
    ),
    async (ctx, [id]) => {
      await ctx.client.requireCapability('skills.download');
      const target = resolve(String(ctx.options.out));
      const requestId =
        typeof ctx.options.requestId === 'string' ? ctx.options.requestId : randomUUID();
      const path = `${ctx.root}/skills/${uuid(id!)}/versions/${ctx.options.versionId}/download`;
      const file = await openFile(target, 'wx', 0o600).catch(() => {
        throw new CliError('output_unavailable', '输出文件已存在或目录不可写，请指定新路径');
      });
      try {
        await journal(ctx.client.server, String(ctx.options.org), requestId, 'POST ' + path);
        errorOutput('请求编号：' + requestId + '\n');
        const result = await ctx.client.download(path, String(ctx.options.org), requestId);
        await file.writeFile(result.bytes);
        await file.close();
        return {
          request_id: requestId,
          org_id: ctx.options.org,
          path: target,
          sha256: result.sha256,
          size: result.bytes.length,
        };
      } catch (error) {
        await file.close();
        await unlink(target).catch(() => {});
        throw error;
      }
    },
  );
  run(
    scoped(experts, 'skill-impact', '查询技能版本更新影响的专家')
      .requiredOption('--skill <uuid>', '技能 UUID', uuid)
      .option('--target-version <uuid>', '目标版本', uuid)
      .option('--source-version <uuid>', '来源版本', uuid)
      .option('--q <text>', '搜索词')
      .option('--page <number>', '页码', positive, '1'),
    (ctx) =>
      read(
        ctx,
        'experts',
        '/skill-impact' +
          query(
            {
              skill_id: ctx.options.skill,
              target_version_id: ctx.options.targetVersion,
              source_version_id: ctx.options.sourceVersion,
              q: ctx.options.q,
              page: ctx.options.page,
            },
            ['skill_id', 'target_version_id', 'source_version_id', 'q', 'page'],
          ),
      ),
  );
  run(
    scoped(experts, 'dependency <id>', '读取指定依赖详情')
      .requiredOption('--kind <kind>', 'skills 或 connectors')
      .option('--version-id <uuid>', '技能版本 UUID', uuid),
    (ctx, [id]) => {
      if (!['skills', 'connectors'].includes(String(ctx.options.kind)))
        throw new CliError('invalid_kind', '请选择 skills 或 connectors');
      return read(
        ctx,
        'experts',
        '/dependencies/' +
          ctx.options.kind +
          '/' +
          uuid(id!) +
          query({ version_id: ctx.options.versionId }, ['version_id']),
      );
    },
  );
  run(scoped(experts, 'dependency-command <id>', '查询精确依赖更新回执'), (ctx, [id]) =>
    read(ctx, 'experts', '/dependency-commands/' + uuid(id!)),
  );
  run(
    writeOptions(
      scoped(
        mcp,
        'run <id>',
        '执行一次工具/提示词/资源测试；工具可能产生真实业务副作用',
      ).requiredOption('--file <json>', 'McpRun JSON'),
    ),
    async (ctx, [id]) => {
      await ctx.client.requireCapability('mcp.run');
      return mutate(ctx, 'mcp', 'POST', `/services/${uuid(id!)}/run`, await fromFile(ctx));
    },
  );
  run(
    scoped(mcp, 'activities', '查询调用或连接记录；不含参数和结果正文')
      .requiredOption('--category <category>', 'call 或 connection')
      .option('--service <uuid>', '服务 UUID', uuid)
      .option('--result <result>', 'success、failed 或 timeout')
      .option('--q <text>', '搜索词')
      .option('--since <time>', '带时区的开始时间')
      .option('--until <time>', '带时区的结束时间')
      .option('--page <number>', '页码', positive, '1'),
    async (ctx) => {
      await ctx.client.requireCapability('mcp.activities');
      return read(
        ctx,
        'mcp',
        '/activities' +
          query({ ...ctx.options, service_id: ctx.options.service }, [
            'category',
            'service_id',
            'result',
            'q',
            'since',
            'until',
            'page',
          ]),
      );
    },
  );
  const contents = mcp.command('contents').description('内置提示词与资源内容维护');
  run(scoped(contents, 'list', '查询内置内容'), async (ctx) => {
    await ctx.client.requireCapability('mcp.contents');
    return read(ctx, 'mcp', '/contents');
  });
  for (const action of ['create', 'update', 'delete']) {
    const command = writeOptions(
      scoped(contents, action + (action === 'create' ? '' : ' <id>'), '维护内置内容'),
    );
    if (action !== 'delete') command.requiredOption('--file <json>', 'McpContentInput JSON');
    run(command, async (ctx, [id]) => {
      await ctx.client.requireCapability('mcp.contents');
      return mutate(
        ctx,
        'mcp',
        action === 'create' ? 'POST' : action === 'update' ? 'PUT' : 'DELETE',
        '/contents' + (id ? '/' + uuid(id) : ''),
        action === 'delete' ? undefined : await fromFile(ctx),
      );
    });
  }
  const oauth = mcp.command('oauth').description('CLI 会话独立发起和确认浏览器授权');
  run(
    writeOptions(
      scoped(
        oauth,
        'start <service-id>',
        '发起授权；浏览器结束后查询 status 并 complete',
      ).option('--no-browser', '仅输出授权 URL，不打开浏览器'),
    ),
    async (ctx, [id]) => {
      await ctx.client.requireCapability('mcp.oauth');
      const response = await mutate(ctx, 'mcp', 'POST', `/services/${uuid(id!)}/oauth/start`);
      const url = object(response.result).authorization_url;
      if (ctx.options.browser !== false && typeof url === 'string') {
        let parsed: URL;
        try {
          parsed = new URL(url);
        } catch {
          throw new CliError('invalid_response', '授权地址无效');
        }
        if (
          parsed.protocol !== 'https:' &&
          !(
            parsed.protocol === 'http:' &&
            ['127.0.0.1', '[::1]', 'localhost'].includes(parsed.hostname)
          )
        )
          throw new CliError('invalid_response', '浏览器授权需要 HTTPS 或本机回环地址');
        try {
          await (runtime.openBrowser || open)(url);
        } catch {
          errorOutput('无法打开浏览器，请打开结果中的 authorization_url。\n');
        }
      }
      return response;
    },
  );
  run(
    scoped(oauth, 'status <attempt-id>', '查询本人发起的授权；pending 时可恢复授权 URL'),
    async (ctx, [id]) => {
      await ctx.client.requireCapability('mcp.oauth');
      return read(ctx, 'mcp', '/oauth/' + uuid(id!));
    },
  );
  for (const action of ['complete', 'cancel']) {
    run(
      writeOptions(
        scoped(
          oauth,
          action + ' <attempt-id>',
          action === 'complete' ? '确认并保存本人上游连接' : '取消尚未完成的授权',
        ),
      ),
      async (ctx, [id]) => {
        await ctx.client.requireCapability('mcp.oauth');
        return mutate(ctx, 'mcp', 'POST', '/oauth/' + uuid(id!) + '/' + action);
      },
    );
  }

  const commands = program.command('commands').description('回查本人在目标组织的写操作');
  run(scoped(commands, 'show <request-id>', '查看原请求执行状态与结果'), async (ctx, [id]) => {
    await ctx.client.requireCapability('commands.show');
    return ctx.client.request('GET', ctx.root + '/commands/' + uuid(id!));
  });
  return program;
}
