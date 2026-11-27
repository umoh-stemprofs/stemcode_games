#!/usr/bin/env node
/**
 * Local Postgres helper (README section 3).
 *
 * `pg_ctl start` blocks until the data directory has been recovered and the
 * postmaster is accepting connections. If the caller gives up first (an editor
 * timeout, Ctrl+C, a CI wrapper), the postmaster is left half-started and every
 * later backend dies at startup with 0xC0000142 / "could not reserve shared
 * memory region". The cluster is not damaged, but it cannot recover until it is
 * stopped cleanly and started again. Starting detached from a short-lived shell
 * and waiting here for readiness avoids creating that state at all.
 *
 * Usage: node scripts/db.mjs start|stop|status
 */
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dataDir = join(root, ".pgdata");
const logFile = join(dataDir, "server.log");
const port = process.env.PGPORT ?? "5433";
const isWindows = process.platform === "win32";
const action = process.argv[2] ?? "status";

const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

function findBinDir() {
  if (process.env.PG_BIN) return process.env.PG_BIN;
  const onPath = spawnSync(isWindows ? "where" : "which", ["pg_ctl"], {
    encoding: "utf8",
  });
  const found = onPath.stdout?.split(/\r?\n/).find(Boolean);
  if (found) return dirname(found.trim());

  // A common Windows install location; harmless to check everywhere.
  const roots = ["C:/Program Files/PostgreSQL", "C:/Users/" + (process.env.USERNAME ?? "") + "/scoop/apps/postgresql/current"];
  for (const base of roots) {
    if (!existsSync(base)) continue;
    try {
      for (const entry of readdirSync(base)) {
        const candidate = join(base, entry, "bin");
        if (existsSync(join(candidate, "pg_ctl.exe"))) return candidate;
      }
    } catch {
      /* not readable; try the next root */
    }
  }
  return null;
}

const binDir = findBinDir();
if (!binDir) {
  console.error("[db] pg_ctl not found. Install PostgreSQL or set PG_BIN to its bin directory.");
  process.exit(1);
}

/**
 * A child backend is started by re-executing postgres.exe, so PATH is what
 * decides which DLLs it loads. Git Bash / scoop entries can shadow the Windows
 * ones and make that child fail with 0xC0000142, so the server is started with
 * a PATH containing only its own bin and the system directories.
 */
const cleanEnv = {
  SystemRoot: process.env.SystemRoot ?? "C:\\Windows",
  SystemDrive: process.env.SystemDrive ?? "C:",
  TEMP: process.env.TEMP ?? "C:\\Windows\\Temp",
  TMP: process.env.TMP ?? "C:\\Windows\\Temp",
  PATH: [binDir, "C:\\Windows\\system32", "C:\\Windows", "C:\\Windows\\System32\\Wbem"].join(";"),
};

const pg = (args, options = {}) =>
  spawnSync(join(binDir, isWindows ? "pg_ctl.exe" : "pg_ctl"), args, {
    cwd: root,
    encoding: "utf8",
    env: cleanEnv,
    ...options,
  });

const serverOptions = `-p ${port} -c listen_addresses=127.0.0.1`;

if (!existsSync(dataDir)) {
  console.error(`[db] no cluster at ${dataDir}. See README section 3 for the one-time initdb.`);
  process.exit(1);
}

if (action === "stop") {
  const result = pg(["-D", dataDir, "-m", "fast", "-w", "-t", "60", "stop"]);
  process.stdout.write(result.stdout ?? "");
  process.stderr.write(result.stderr ?? "");
  process.exit(result.status ?? 1);
}

if (action === "status") {
  const status = pg(["-D", dataDir, "status"]);
  if (status.status === 0) {
    console.log(`[db] running on port ${port}`);
    process.exit(0);
  }
  console.log(`[db] not running (start it with \`npm run db:start\`)`);
  process.exit(1);
}

if (action === "start") {
  const status = pg(["-D", dataDir, "status"]);
  if (status.status === 0) {
    console.log(`[db] already running on port ${port}`);
    process.exit(0);
  }

  // A crash-looping cluster reports "running" only while a postmaster lives;
  // a stale pid file from a killed launcher reports nothing usable. Starting
  // over is safe: recovery replays the WAL either way.
  const start = spawnSync(
    join(binDir, isWindows ? "pg_ctl.exe" : "pg_ctl"),
    ["-D", dataDir, "-o", serverOptions, "-l", logFile, "-w", "-t", "180", "start"],
    { cwd: root, stdio: "ignore", env: cleanEnv, detached: true, windowsHide: true },
  );

  if (start.error) {
    console.error(`[db] could not launch pg_ctl: ${start.error.message}`);
    process.exit(1);
  }

  // `detached` + ignored stdio means the exit code is not observable; readiness
  // is. Poll for the port rather than trusting a banner.
  const isReady = () => {
    const probe = spawnSync(
      join(binDir, isWindows ? "psql.exe" : "psql"),
      ["-h", "127.0.0.1", "-p", port, "-U", "postgres", "-d", "postgres", "-tAc", "select 1"],
      { encoding: "utf8", env: cleanEnv, timeout: 10_000 },
    );
    return probe.status === 0 && (probe.stdout ?? "").trim() === "1";
  };

  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    if (isReady()) {
      console.log(`[db] ready on 127.0.0.1:${port}`);
      process.exit(0);
    }
    sleep(1000);
  }

  console.error("[db] Postgres did not become ready. Last log lines:");
  const tail = spawnSync(
    isWindows ? "powershell" : "tail",
    isWindows
      ? ["-NoProfile", "-Command", `Get-Content -Tail 20 '${logFile}'`]
      : ["-n", "20", logFile],
    { encoding: "utf8" },
  );
  process.stderr.write(tail.stdout ?? "");
  process.exit(1);
}

console.error(`[db] unknown action "${action}". Use start, stop or status.`);
process.exit(2);
