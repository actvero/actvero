import { writeFile, readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { buildProgram } from "../dist/commands.js";
import { Client } from "../dist/client.js";
import { login } from "../dist/login.js";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
let state = {};
const store = {
  load: async () => structuredClone(state),
  save: async (value) => {
    state = structuredClone(value);
  },
  clear: async () => {
    state = {};
  },
  locked: async (fn) => fn(),
};
const client = new Client(config.server, store);
async function command(args) {
  let result;
  const p = buildProgram({
    client: () => client,
    output: (s) => {
      result = JSON.parse(s);
    },
    errorOutput: () => {},
    journal: async () => {},
  });
  await p.parseAsync(
    ["--server", config.server, ...args, "--org", config.org, "--json"],
    { from: "user" },
  );
  return result;
}
try {
  await login(client, true, false, async (target) => {
    const consent = new URLSearchParams(new URL(target).hash.slice(1));
    const approval = await fetch(config.server + '/api/v1/cli-authorization/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: config.server,
        Cookie: config.browser_cookie, 'X-CSRF-Token': config.browser_csrf },
      body: JSON.stringify({ attempt_id: consent.get('attempt_id'), state: consent.get('state'),
        approve: true, org_ids: [config.org], scope: 'management:read management:write' }),
    });
    if (approval.status !== 200) throw Error('browser approval failed');
    const authorization = new URL((await approval.json()).redirect_url);
    const callback = new URL(authorization.searchParams.get("redirect_uri"));
    callback.search = new URLSearchParams({
      state: authorization.searchParams.get("state"),
      iss: config.issuer,
      code: "one-time-code",
    }).toString();
    const result = await fetch(callback);
    if (result.status !== 200) throw Error("callback failed");
  });
  const created = await command([
    "skills",
    "import",
    config.zip,
    "--version",
    "1.0.0",
  ]);
  const s = created.result;
  const published = await command([
    "skills",
    "publish",
    s.id,
    "--version-id",
    s.versions[0].id,
    "--revision",
    String(s.revision),
  ]);
  if (!published.result.default_version_id) throw Error("skill not published");
  await command([
    "skills",
    "file",
    s.id,
    "--version-id",
    s.versions[0].id,
    "--path",
    "test-skill/SKILL.md",
  ]);
  await command(["skills", "icons"]);
  const download = await command([
    "skills",
    "download",
    s.id,
    "--version-id",
    s.versions[0].id,
    "--out",
    config.zip + ".download",
  ]);
  assert.deepEqual(await readFile(download.path), await readFile(config.zip));
  const distributions = await command([
    "skills",
    "distributions",
    "--skill",
    s.id,
  ]);
  assert.equal(distributions.result.total, 1);
  for (const kind of ["skills", "experts"]) {
    const categories = await command([
      kind,
      "categories",
      "create",
      "--name",
      "CLI temporary category",
    ]);
    const category = categories.result.find(
      (c) => c.name === "CLI temporary category",
    );
    const renamed = await command([
      kind,
      "categories",
      "rename",
      category.id,
      "--revision",
      String(category.revision),
      "--name",
      "Renamed",
    ]);
    const current = renamed.result.find((c) => c.id === category.id);
    await command([
      kind,
      "categories",
      "delete",
      current.id,
      "--revision",
      String(current.revision),
      "--count",
      "0",
      "--target",
      "uncategorized",
    ]);
  }
  await command([
    "experts",
    "skill-impact",
    "--skill",
    s.id,
    "--target-version",
    s.versions[0].id,
  ]);
  await command([
    "experts",
    "dependency",
    s.id,
    "--kind",
    "skills",
    "--version-id",
    s.versions[0].id,
  ]);
  const mcp = await command(["mcp", "create", "--file", config.mcp]);
  const found = await command(["mcp", "show", mcp.result.id]);
  if (found.result.name !== "Fixture MCP") throw Error("mcp mismatch");
  const dataFile = config.mcp + ".content";
  const prompt = {
    service_id: mcp.result.id,
    kind: "prompts",
    name: "hello",
    body: "Hello {{name}}",
    arguments: ["name"],
  };
  await writeFile(dataFile, JSON.stringify(prompt));
  const saved = await command([
    "mcp",
    "contents",
    "create",
    "--file",
    dataFile,
  ]);
  await command(["mcp", "contents", "list"]);
  await writeFile(
    dataFile,
    JSON.stringify({ ...prompt, body: "Welcome {{name}}" }),
  );
  await command([
    "mcp",
    "contents",
    "update",
    saved.result.id,
    "--file",
    dataFile,
  ]);
  await writeFile(
    dataFile,
    JSON.stringify({
      kind: "prompts",
      key: "hello",
      arguments: { name: "Node" },
    }),
  );
  const result = await command([
    "mcp",
    "run",
    mcp.result.id,
    "--file",
    dataFile,
  ]);
  assert.ok(JSON.stringify(result).includes("Welcome Node"));
  const activity = await command([
    "mcp",
    "activities",
    "--category",
    "call",
    "--service",
    mcp.result.id,
  ]);
  assert.equal(activity.result.total, 1);
  await command(["mcp", "contents", "delete", saved.result.id]);
  const oauthService = await command(["mcp", "create", "--file", config.oauth]);
  const attempt = await command([
    "mcp",
    "oauth",
    "start",
    oauthService.result.id,
    "--no-browser",
  ]);
  const state = new URL(attempt.result.authorization_url).searchParams.get(
    "state",
  );
  const callback = await fetch(
    config.server +
      "/api/v1/management/mcp/oauth/callback?" +
      new URLSearchParams({ state, code: "fixture-code" }),
  );
  assert.equal(callback.status, 200);
  const staged = await command(["mcp", "oauth", "status", attempt.result.id]);
  assert.equal(staged.result.status, "awaiting_confirmation");
  const completed = await command([
    "mcp",
    "oauth",
    "complete",
    attempt.result.id,
  ]);
  assert.equal(completed.result.status, "completed");
  const next = await command([
    "mcp",
    "oauth",
    "start",
    oauthService.result.id,
    "--no-browser",
  ]);
  const cancelled = await command(["mcp", "oauth", "cancel", next.result.id]);
  assert.equal(cancelled.result.status, "cancelled");
  const expert = await command(["experts", "create", "--file", config.expert]);
  const release = await command([
    "experts",
    "publish",
    expert.result.id,
    "--revision",
    String(expert.result.revision),
    "--version",
    "1.0.0",
  ]);
  const receipt = await command(["commands", "show", release.request_id]);
  if (receipt.result.status !== "succeeded") throw Error("missing receipt");
  await client.logout();
  process.stdout.write(
    JSON.stringify({
      ok: true,
      skill: s.id,
      mcp: mcp.result.id,
      expert: expert.result.id,
    }),
  );
} catch (error) {
  process.stderr.write(
    JSON.stringify({ code: error.code || "failed", message: error.message }),
  );
  process.exitCode = 1;
}
