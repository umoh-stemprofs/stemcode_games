import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end smoke suite (P11-T05, and the two-browser half of P8-T19).
 *
 * The suite talks to the real stack on one origin, exactly like a learner:
 * Next on :3000, which rewrites `/api/*` to FastAPI on :8000. It therefore
 * needs a **seeded** database, and it says so rather than pretending:
 *
 *     npm run migrate && npm run seed
 *     npm run dev:api        # terminal 1
 *     npm run dev:web        # terminal 2
 *     npm run test:e2e       # terminal 3
 *
 * `workers: 1` and serial mode are deliberate. The tests share one seeded
 * school, and the two-player test would otherwise race another test for the
 * same learner's single open seat (D-26).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // A learner on a school laptop, not a phone: the games are laptop-first.
    viewport: { width: 1280, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      // `channel: "chromium"` runs the full browser in its new headless mode.
      // Without it Playwright wants a second, separate "headless shell" download,
      // which is one more 100 MB that adds nothing to a smoke test.
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
    },
  ],
});
