import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

// Only this unpatched development-tool advisory is deferred. Never suppress
// unrelated findings or production dependencies, including transitive ones.
const deferred = "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm";
const result = spawnSync(process.execPath, [process.env.npm_execpath,
  "audit", "--json", "--registry=https://registry.npmjs.org"], { encoding: "utf8" });
if (result.error || ![0, 1].includes(result.status)) {
  console.error(result.error || result.stderr || "Dependency audit failed.");
  process.exit(1);
}
const report = JSON.parse(result.stdout);
if (report.error || !report.vulnerabilities || !report.metadata) {
  throw new Error("Dependency audit returned an invalid report.");
}
const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url)));
const findings = report.vulnerabilities;
function isDeferred(name, visited = new Set()) {
  const item = findings[name];
  if (!item || visited.has(name) || !item.nodes?.length || !item.via?.length) return false;
  if (!item.nodes.every((path) => lock.packages[path]?.dev === true)) return false;
  const next = new Set(visited).add(name);
  return item.via.every((source) => typeof source === "string"
    ? isDeferred(source, next)
    : name === "braces" && source.url === deferred);
}
let blocked = false;
for (const [name, item] of Object.entries(findings)) {
  if (isDeferred(name)) {
    console.warn(`UNPATCHED development dependency: ${name} (${item.severity}); ${deferred}`);
  } else {
    blocked = true;
    console.error(`BLOCKED: ${name} (${item.severity})`);
    console.error(JSON.stringify(item.via, null, 2));
  }
}
console.log(JSON.stringify(report.metadata.vulnerabilities));
process.exitCode = blocked ? 1 : 0;
