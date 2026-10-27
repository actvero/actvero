import { cp, readFile, readdir, mkdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const source = fileURLToPath(new URL('../../agent-skills/actvero-management/', import.meta.url));
const target = fileURLToPath(new URL('../skills/actvero-management/', import.meta.url));
async function inventory(root, relative = '') {
  const entries = [];
  for (const item of await readdir(join(root, relative), { withFileTypes: true })) {
    const path = join(relative, item.name);
    if (item.isDirectory()) entries.push(...await inventory(root, path));
    else if (item.isFile()) entries.push(path);
    else throw new Error('Skill sources must contain only ordinary files and directories');
  }
  return entries.sort();
}
if (process.argv.includes('--check')) {
  const paths = await inventory(source);
  if (JSON.stringify(paths) !== JSON.stringify(await inventory(target))) throw new Error('Bundled Skill inventory differs; run npm run sync:skill');
  for (const path of paths) if (!(await readFile(join(source, path))).equals(await readFile(join(target, path)))) throw new Error('Bundled Skill differs: ' + path);
  process.stdout.write('Bundled Skill matches its source.\n');
} else {
  await inventory(source);
  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });
  await cp(source, target, { recursive: true });
}
