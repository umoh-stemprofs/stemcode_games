#!/usr/bin/env node
/**
 * Cross-platform Python runner (P0-T02).
 *
 * Every Python command goes through this script so contributors never need
 * `make`, never activate a venv by hand, and always get the same PYTHONPATH.
 * It prefers `.venv` and falls back to the system interpreter.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";
const venvPython = join(root, ".venv", isWindows ? "Scripts/python.exe" : "bin/python3");
const python = existsSync(venvPython) ? venvPython : isWindows ? "python" : "python3";

if (!existsSync(venvPython)) {
  console.warn(
    "[py] .venv not found; using the system interpreter. " +
      "Run `python -m venv .venv` and install dependencies (see README).",
  );
}

const result = spawnSync(python, process.argv.slice(2), {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    // `app` and `tests` live under api/, so api/ must be importable.
    PYTHONPATH: [join(root, "api"), process.env.PYTHONPATH].filter(Boolean).join(isWindows ? ";" : ":"),
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  },
});

if (result.error) {
  console.error(`[py] failed to start ${python}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
