import { cp, mkdir, readdir, readFile, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CliError } from './errors.js';

const topics: Record<string, string> = {
  overview: 'SKILL.md',
  bootstrap: 'references/bootstrap.md',
  operations: 'references/operations.md',
  skills: 'references/skills.md',
  mcp: 'references/mcp.md',
  experts: 'references/experts.md',
  recovery: 'references/recovery.md',
  commands: 'references/commands.md',
};

async function packageRoot(): Promise<string> {
  let directory = dirname(fileURLToPath(import.meta.url));
  for (let depth = 0; depth < 4; depth++) {
    try {
      const pkg = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'));
      if (pkg.name === '@actvero/cli') return directory;
    } catch {
      /* Search only this installed module's ancestors. */
    }
    directory = dirname(directory);
  }
  throw new CliError('package_incomplete', 'CLI 安装不完整，请重新安装同一版本');
}

export async function skillPath(): Promise<string> {
  return join(await packageRoot(), 'skills', 'actvero-management');
}

export function guideTopics(): string[] {
  return Object.keys(topics);
}

export async function guide(topic: string): Promise<unknown> {
  if (!Object.hasOwn(topics, topic))
    throw new CliError('unknown_guide', '请先使用 guide list 查询手册主题');
  return { topic, content: await readFile(join(await skillPath(), topics[topic]!), 'utf8') };
}

export async function installSkill(parent: string): Promise<unknown> {
  const source = await skillPath();
  await readFile(join(source, 'SKILL.md'), 'utf8');
  const target = join(resolve(parent), 'actvero-management');
  await mkdir(dirname(target), { recursive: true });
  try {
    await mkdir(target);
  } catch {
    throw new CliError(
      'skill_target_unavailable',
      'Skill 目录已存在或不可写；不会覆盖，请先检查已有内容',
    );
  }
  try {
    for (const name of await readdir(source)) {
      await cp(join(source, name), join(target, name), {
        recursive: true,
        force: false,
        errorOnExist: true,
      });
    }
  } catch (error) {
    await rm(target, { recursive: true, force: true });
    throw error;
  }
  return { name: 'actvero-management', path: target, installed: true };
}

interface Catalog {
  resource_contract_version: number;
  minimum_migration: string;
  source_sha256: string;
  roots: string[];
  definitions: Record<string, unknown>;
}

async function catalog(): Promise<Catalog> {
  return JSON.parse(
    await readFile(join(await packageRoot(), 'schemas', 'catalog.json'), 'utf8'),
  );
}

export async function schemaList(): Promise<unknown> {
  const { definitions, ...metadata } = await catalog();
  return { ...metadata, schemas: Object.keys(definitions).sort() };
}

export async function schema(name: string): Promise<unknown> {
  const data = await catalog();
  if (!Object.hasOwn(data.definitions, name))
    throw new CliError('unknown_schema', '请先使用 schema list 查询准确名称');
  const definitions: Record<string, unknown> = {};
  const visit = (key: string) => {
    if (Object.hasOwn(definitions, key)) return;
    definitions[key] = data.definitions[key];
    const scan = (value: unknown): void => {
      if (!value || typeof value !== 'object') return;
      for (const [field, child] of Object.entries(value)) {
        if (field === '$ref' && typeof child === 'string' && child.startsWith('#/$defs/'))
          visit(child.slice('#/$defs/'.length));
        else scan(child);
      }
    };
    scan(definitions[key]);
  };
  visit(name);
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $ref: '#/$defs/' + name,
    $defs: definitions,
  };
}

const examples = ['expert', 'mcp', 'mcp-run', 'skill-metadata', 'mcp-builtin'];
export function exampleNames(): string[] {
  return [...examples];
}
export async function example(name: string): Promise<unknown> {
  if (!examples.includes(name))
    throw new CliError('unknown_example', '请先使用 example list 查询示例');
  return JSON.parse(
    await readFile(join(await packageRoot(), 'examples', name + '.json'), 'utf8'),
  );
}
