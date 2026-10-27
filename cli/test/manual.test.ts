import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildProgram } from '../src/commands.js';
import { Client } from '../src/client.js';
import { exampleNames, guideTopics, installSkill, schema, skillPath } from '../src/manual.js';
import { MemoryStore, reply } from './helpers.js';

async function offline(args: string[]) {
  let output = '';
  await buildProgram({
    client: () => {
      throw new Error('Offline command must not construct a client');
    },
    journal: async () => {
      throw new Error('Offline command must not journal');
    },
    output: (value) => {
      output += value;
    },
  }).parseAsync(args, { from: 'user' });
  return JSON.parse(output);
}

test('manual, schema and examples work with no server or credential access', async () => {
  const guides = await offline(['guide', 'list']);
  assert.deepEqual(guides.topics, guideTopics());
  for (const topic of guides.topics) {
    const value = await offline(['guide', 'show', topic, '--json']);
    assert.ok(value.content.length > 100);
  }
  for (const name of exampleNames()) {
    const value = await offline(['example', 'show', name]);
    assert.equal(typeof value, 'object');
  }
  const path = await offline(['agent-skill', 'path']);
  assert.match(await readFile(join(path.path, 'SKILL.md'), 'utf8'), /name: actvero-management/);
});

test('all bundled schemas are self-contained and use only bundled references', async () => {
  const list = await offline(['schema', 'list']);
  assert.equal(list.resource_contract_version, 1);
  assert.match(list.source_sha256, /^[a-f0-9]{64}$/);
  assert.ok(list.schemas.includes('ManagementOAuthView'));
  for (const name of list.schemas) {
    const value = (await schema(name)) as { $defs: Record<string, unknown> };
    const scan = (node: unknown) => {
      if (!node || typeof node !== 'object') return;
      for (const [key, child] of Object.entries(node)) {
        if (key === '$ref') {
          assert.match(String(child), /^#\/\$defs\//);
          assert.ok(Object.hasOwn(value.$defs, String(child).slice('#/$defs/'.length)));
        } else scan(child);
      }
    };
    scan(value);
  }
});

test('offline names cannot read arbitrary package or filesystem paths', async () => {
  for (const [group, name] of [
    ['guide', '../package.json'],
    ['guide', '__proto__'],
    ['schema', 'constructor'],
    ['example', '../../package.json'],
  ])
    await assert.rejects(offline([group!, 'show', name!]), /请先使用/);
});

test('Skill install copies all references and never overwrites an existing skill', async () => {
  const parent = await mkdtemp(join(tmpdir(), 'actvero-agent-skill-'));
  try {
    const value = await offline(['agent-skill', 'install', '--to', parent]);
    assert.equal(value.path, join(parent, 'actvero-management'));
    const source = await skillPath();
    assert.equal(
      await readFile(join(value.path, 'references/mcp.md'), 'utf8'),
      await readFile(join(source, 'references/mcp.md'), 'utf8'),
    );
    await writeFile(join(value.path, 'SKILL.md'), 'user customized content');
    await assert.rejects(installSkill(parent), { code: 'skill_target_unavailable' });
    assert.equal(
      await readFile(join(value.path, 'SKILL.md'), 'utf8'),
      'user customized content',
    );
  } finally {
    await rm(parent, { recursive: true, force: true });
  }
});

test('platform info is unauthenticated and does not read a credential store', async () => {
  const store = new MemoryStore();
  store.load = async () => {
    throw new Error('must not read tokens');
  };
  let calls = 0;
  const client = new Client('https://example.com', store, async (url, init) => {
    calls++;
    assert.equal(String(url), 'https://example.com/api/v1/management/metadata');
    assert.equal(init?.method, 'GET');
    assert.equal((init?.headers as Record<string, string>).Authorization, undefined);
    return reply({ resource_contract_version: 1, capabilities: ['skills.read'] });
  });
  let output = '';
  await buildProgram({
    client: () => client,
    output: (value) => {
      output += value;
    },
  }).parseAsync(['platform', 'info', '--server', 'https://example.com', '--json'], {
    from: 'user',
  });
  assert.equal(calls, 1);
  assert.deepEqual(JSON.parse(output).capabilities, ['skills.read']);
});

test('CLI reports the version from its installed package metadata', async () => {
  const metadata = JSON.parse(await readFile(join(await skillPath(), '..', '..', 'package.json'), 'utf8'));
  assert.equal(buildProgram().version(), metadata.version);
});
