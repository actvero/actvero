import { readdir, readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join, relative, extname } from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../", import.meta.url));
const policy = JSON.parse(
  await readFile(join(root, "scripts/public-policy.json"), "utf8"),
);
const ignored = new Set([
  ".git",
  ".local",
  "node_modules",
  "dist",
  "dist-test",
  "coverage",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
]);
const errors = [];
const rules = [
  ["private-key", /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
  [
    "access-token",
    /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{25,})\b/,
  ],
  ["personal-path", /\/(?:Users|home)\/[A-Za-z0-9_.-]+\//],
];
const processName =
  /(?:^|[-_/])(handoff|progress|verification|dispatch|research|session-notes|conversation)(?:[-_/.]|$)/i;
async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const path = join(directory, entry.name);
    const name = relative(root, path).replaceAll("\\", "/");
    if (entry.isSymbolicLink()) {
      errors.push(name + ": symlink-not-reviewed");
      continue;
    }
    if (entry.isDirectory()) {
      await walk(path);
      continue;
    }
    if (
      entry.name.startsWith(".env") ||
      /\.(?:tgz|dump|log|sqlite|pem|key)$/.test(name)
    )
      errors.push(name + ": private-or-generated-file");
    if (processName.test(name)) errors.push(name + ": process-document");
    if (
      [".md", ".txt", ".pdf", ".docx"].includes(extname(name)) &&
      !policy.documents.includes(name)
    )
      errors.push(name + ": unregistered-document");
    const content = await readFile(path, "utf8");
    for (const [label, pattern] of rules)
      if (pattern.test(content)) errors.push(name + ": " + label);
    const candidates = new Set(
      content.match(/[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{2,}/g) || [],
    );
    for (const token of [...candidates]) {
      for (const part of token.split(/[_.-]/)) candidates.add(part);
      candidates.add(token.replace(/[_.-]/g, ""));
    }
    if (
      [...candidates].some((value) =>
        policy.restricted_identifier_sha256.includes(
          createHash("sha256").update(value.toLowerCase()).digest("hex"),
        ),
      )
    )
      errors.push(name + ": restricted-identifier");
  }
}
await walk(root);
if (errors.length) {
  process.stderr.write(errors.join("\n") + "\n");
  process.exitCode = 1;
} else process.stdout.write("Public source check passed.\n");
