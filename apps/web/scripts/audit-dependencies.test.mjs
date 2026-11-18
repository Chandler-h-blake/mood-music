import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const deferred = "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm";
function audit(vulnerabilities, status = 1) {
  const directory = mkdtempSync(join(tmpdir(), "moodmusic-audit-"));
  try {
    const npm = join(directory, "npm.mjs");
    const report = { vulnerabilities, metadata: { vulnerabilities: {} } };
    writeFileSync(npm, `console.log(${JSON.stringify(JSON.stringify(report))}); process.exit(${status});`);
    return spawnSync(process.execPath, [fileURLToPath(new URL("./audit-dependencies.mjs", import.meta.url))],
      { env: { ...process.env, npm_execpath: npm }, encoding: "utf8" });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}
const finding = (url = deferred, node = "node_modules/braces") => ({
  severity: "high", nodes: [node], via: [{ url }],
});
test("reports the unpatched braces development advisory without blocking", () => {
  const result = audit({ braces: finding() });
  assert.equal(result.status, 0);
  assert.match(result.stderr, /UNPATCHED/);
});

test("reports the unpatched picomatch advisory and development dependents", () => {
  const url = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
  const picomatch = finding(url, "node_modules/picomatch");
  const vite = { ...finding(url, "node_modules/vite"), via: ["picomatch"] };
  const result = audit({ picomatch, vite });
  assert.equal(result.status, 0);
  assert.match(result.stderr, /GHSA-fc5q-39xc-vjpf/);
});

test("blocks additional picomatch advisories and production dependents", () => {
  const url = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
  const picomatch = finding(url, "node_modules/picomatch");
  const production = { ...finding(url, "node_modules/react"), via: ["picomatch"] };
  assert.equal(audit({ picomatch, production }).status, 1);
  picomatch.via.push({ url: "https://github.com/advisories/new-vulnerability" });
  assert.equal(audit({ picomatch }).status, 1);
});
test("blocks a new advisory even alongside the deferred advisory", () => {
  const braces = finding();
  braces.via.push({ url: "https://github.com/advisories/new-vulnerability" });
  assert.equal(audit({ braces }).status, 1);
});
test("never defers production dependencies", () => {
  assert.equal(audit({ braces: finding(deferred, "node_modules/react") }).status, 1);
});
test("blocks unresolved dependency references", () => {
  assert.equal(audit({ tool: { ...finding(), via: ["missing"] } }).status, 1);
});
test("blocks audit service failures", () => {
  assert.equal(audit({}, 2).status, 1);
});
