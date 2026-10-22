import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

// Development-only: pass an explicitly selected platform contract. Build/install never
// read another repository or contact a server.
const args = process.argv.slice(2);
const check = args[0] === "--check";
if (check) args.shift();
if (args.length !== 1)
  throw new Error(
    "Usage: node scripts/sync-schemas.mjs [--check] <openapi.json>",
  );
const raw = await readFile(args[0], "utf8");
const source = JSON.parse(raw).components.schemas;
const roots = [
  "Metadata",
  "Me",
  "Organization",
  "Organizations",
  "CommandStatus",
  "ManagementOAuthView",
  "SkillImport",
  "SkillUpdate",
  "SkillAction",
  "SkillView",
  "SkillPreview",
  "SkillOverview",
  "SkillFileContent",
  "SkillDistributionPage",
  "SkillIconOption",
  "CategoryName",
  "CategoryRename",
  "CategoryMove",
  "CategoryDelete",
  "ManagedSkillCategory",
  "ExpertCategoryName",
  "ExpertCategoryRename",
  "ExpertCategoryMove",
  "ExpertCategoryDelete",
  "ManagedExpertCategory",
  "ExpertSave",
  "ExpertUpdate",
  "ExpertScope",
  "ExpertPublish",
  "ExpertRevision",
  "ExpertSkillRefresh",
  "ExpertView",
  "ExpertDependencyOption",
  "ExpertSkillImpactView",
  "DependencyCommandView",
  "McpServiceWrite",
  "McpServiceUpdate",
  "McpPresentationUpdate",
  "McpPolicyInput",
  "McpCredentials",
  "McpRun",
  "McpImport",
  "McpImportRequest",
  "McpContentInput",
  "McpServiceView",
  "McpCapabilities",
  "McpActivityPage",
  "McpResult",
].sort();
const definitions = {};
function visit(name) {
  if (Object.hasOwn(definitions, name)) return;
  if (!Object.hasOwn(source, name)) throw new Error("Missing schema: " + name);
  definitions[name] = null;
  definitions[name] = JSON.parse(
    JSON.stringify(source[name], (key, value) => {
      if (key === "$ref") {
        const prefix = "#/components/schemas/";
        if (!value.startsWith(prefix))
          throw new Error("External schema ref: " + value);
        const target = value.slice(prefix.length);
        visit(target);
        return "#/$defs/" + target;
      }
      return value;
    }),
  );
}
roots.forEach(visit);
const directory = fileURLToPath(new URL("../schemas/", import.meta.url));
const content =
  JSON.stringify(
    {
      resource_contract_version: 1,
      minimum_migration: "112g_management_mcp_oauth",
      source_sha256: createHash("sha256").update(raw).digest("hex"),
      roots,
      definitions: Object.fromEntries(
        Object.entries(definitions).sort(([a], [b]) => a.localeCompare(b)),
      ),
    },
    null,
    2,
  ) + "\n";
if (check) {
  if ((await readFile(directory + "catalog.json", "utf8")) !== content)
    throw new Error("CLI schema snapshot is stale; run make generate-api.");
  process.stdout.write("CLI schema snapshot matches the platform contract.\n");
} else {
  await mkdir(directory, { recursive: true });
  await writeFile(directory + "catalog.json", content);
  process.stdout.write(
    "Wrote " + Object.keys(definitions).length + " bundled schemas.\n",
  );
}
