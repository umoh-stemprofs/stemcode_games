#!/usr/bin/env node
/**
 * Generate the TypeScript client from the running API's OpenAPI schema (P0-T07).
 *
 * The FastAPI schema is the contract (D-20): the TypeScript side is generated,
 * never hand-written, and CI fails when the committed output is stale.
 *
 * Usage: start the API (`npm run dev:api`), then `npm run gen:api`.
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "web", "lib", "api");
const schemaPath = join(outDir, "openapi.json");
const tsPath = join(outDir, "schema.ts");
const SOURCE = process.env.API_OPENAPI_URL ?? "http://127.0.0.1:8000/api/openapi.json";

async function fetchSchema() {
  let lastError;
  for (let attempt = 1; attempt <= 20; attempt += 1) {
    try {
      const response = await fetch(SOURCE);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  throw new Error(`could not read ${SOURCE}: ${lastError?.message ?? "unknown error"}`);
}

const schema = await fetchSchema();
mkdirSync(outDir, { recursive: true });
writeFileSync(schemaPath, `${JSON.stringify(schema, null, 2)}\n`);

// Run the CLI's JavaScript entry with the current Node binary. Going through a
// shell would re-split these arguments on the workspace path, which is allowed
// to contain spaces ("STEMs Prof Files"), so no shell here.
const cliPath = join(root, "web", "node_modules", "openapi-typescript", "bin", "cli.js");

if (!existsSync(cliPath)) {
  console.error("[gen:api] openapi-typescript is missing. Run: npm run install:web");
  process.exit(1);
}

const generated = spawnSync(process.execPath, [cliPath, schemaPath, "-o", tsPath], {
  cwd: root,
  stdio: "inherit",
});

if (generated.status !== 0) {
  console.error("[gen:api] openapi-typescript failed");
  process.exit(generated.status ?? 1);
}

console.log(`[gen:api] wrote ${tsPath}`);
