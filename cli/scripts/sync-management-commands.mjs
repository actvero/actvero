import { mkdir, readFile, writeFile } from 'node:fs/promises';

const args = process.argv.slice(2);
const check = args[0] === '--check';
if (check) args.shift();
if (args.length !== 1)
  throw new Error('用法：node cli/scripts/sync-management-commands.mjs [--check] <openapi.json>');

const spec = JSON.parse(await readFile(args[0], 'utf8'));
const mapping = JSON.parse(await readFile(new URL('./management-commands.json', import.meta.url), 'utf8'));
const prefix = '/api/v1/management';
const operations = new Map();
for (const [path, item] of Object.entries(spec.paths)) {
  for (const [method, operation] of Object.entries(item)) {
    const id = operation.operationId;
    if (!id) continue;
    if (operations.has(id)) throw new Error(`重复的 operationId：${id}`);
    operations.set(id, { path, method: method.toUpperCase(), operation });
  }
}

function queryOption(parameter, sendDefaults) {
  const { name, required, description, schema } = parameter;
  const variants = schema.anyOf?.filter((variant) => variant.type !== 'null') ?? [schema];
  const type = variants[0];
  if (variants.length !== 1 || ['org', 'file', 'server', 'json'].includes(name))
    throw new Error(`查询参数 ${name} 需要专门的命令适配`);
  const positiveInteger = type.type === 'integer' && type.minimum === 1;
  if ((!positiveInteger && type.type !== 'string') || !/^[a-z][a-z0-9]*$/.test(name))
    throw new Error(`查询参数 ${name} 需要专门的命令适配`);
  return {
    name,
    description: description || name,
    required,
    positiveInteger,
    default: sendDefaults.includes(name) ? schema.default : null,
  };
}

function commandFor(resource, entry) {
  const target = operations.get(entry.operationId);
  if (!target) throw new Error(`OpenAPI 缺少操作：${entry.operationId}`);
  const { path, method, operation } = target;
  const resourcePath = `${prefix}/organizations/{org_id}/${resource}`;
  if (path !== resourcePath && !path.startsWith(resourcePath + '/'))
    throw new Error(`接口不在对应的组织管理路径内：${path}`);

  const parameters = operation.parameters ?? [];
  if (parameters.some((parameter) => !['path', 'query', 'header'].includes(parameter.in)))
    throw new Error(`接口参数需要专门的命令适配：${entry.operationId}`);
  const write = method !== 'GET';
  const headers = parameters.filter((parameter) => parameter.in === 'header');
  if (
    write
      ? headers.length !== 1 || headers[0].name !== 'X-Management-Request-ID' || !headers[0].required
      : headers.length !== 0
  ) throw new Error(`操作的回执规则不受支持：${entry.operationId}`);

  const aliases = entry.arguments ?? {};
  const pathNames = [...path.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]);
  const pathParameters = parameters.filter((parameter) => parameter.in === 'path');
  if (
    pathParameters.length !== pathNames.length ||
    pathNames.some((name) => !pathParameters.some(
      (parameter) => parameter.name === name && parameter.required && parameter.schema.format === 'uuid',
    )) ||
    Object.keys(aliases).length !== pathNames.length - 1 ||
    pathNames.some((name) => name !== 'org_id' && !/^[a-z][a-z0-9-]*$/.test(aliases[name] ?? ''))
  ) throw new Error(`操作的位置参数映射不匹配：${entry.operationId}`);

  const body = operation.requestBody;
  const schemaRef = body?.content?.['application/json']?.schema?.$ref;
  if (body && (!write || !body.required || !schemaRef?.startsWith('#/components/schemas/')))
    throw new Error(`请求体需要专门的命令适配：${entry.operationId}`);

  return {
    method,
    path: path.slice(prefix.length),
    description: operation.description || operation.summary,
    write,
    arguments: pathNames.filter((name) => name !== 'org_id').map((name) => ({ name, alias: aliases[name] })),
    query: parameters
      .filter((parameter) => parameter.in === 'query')
      .map((parameter) => queryOption(parameter, entry.sendDefaults ?? [])),
    body: schemaRef?.split('/').at(-1) ?? null,
  };
}

const catalog = Object.fromEntries(Object.entries(mapping).map(([resource, commands]) => [
  resource,
  Object.fromEntries(Object.entries(commands).map(([name, entry]) => [name, commandFor(resource, entry)])),
]));
const directory = new URL('../src/generated/', import.meta.url);
const file = new URL('management-commands.ts', directory);
const content = '// 由 OpenAPI 生成，请运行 make generate-api 更新。\n' +
  `export const managementCommands = ${JSON.stringify(catalog, null, 2)} as const;\n`;
if (check) {
  if (await readFile(file, 'utf8') !== content)
    throw new Error('CLI 命令契约已过期，请运行 make generate-api');
} else {
  await mkdir(directory, { recursive: true });
  await writeFile(file, content);
}
