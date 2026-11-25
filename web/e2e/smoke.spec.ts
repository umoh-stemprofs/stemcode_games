import { test, expect, type Page } from "@playwright/test";

/**
 * The smoke suite a launch audit asks for: the four journeys that, if broken,
 * mean the product does not work — sign in, play a game to its end, get into a
 * match with another learner, and end that match on purpose.
 *
 * It runs against the seeded demo school: `A-1001` is Amara and `A-1002` is
 * Bayo, both in Year 5A, both with PIN 2468. Assertions use the words on the
 * screen, never a CSS class, so a redesign does not silently break the test.
 */

test.describe.configure({ mode: "serial" });

const PIN = "2468";
// A code signs you in; a name is what the other learner sees.
const AMARA = { code: "A-1001", name: "Amara" };
const BAYO = { code: "A-1002", name: "Bayo" };

/**
 * Clear a game left open by an interrupted run.
 *
 * D-26 allows one open play session per learner, so a half-finished run poisons
 * the next one: the invite button answers "you have a game open somewhere else"
 * and the test hangs on a URL that never changes. Cleaning up through the same
 * API the page uses keeps the suite repeatable without touching the database.
 */
async function clearLeftovers(page: Page): Promise<void> {
  await page.evaluate(async () => {
    // Old invitations pile up in a seeded school and would make every text
    // assertion ambiguous; declining them is what the inbox button does.
    const inbox = await fetch("/api/games/inbox", { cache: "no-store" });
    if (inbox.ok) {
      const data = (await inbox.json()) as {
        invites?: { invitation_id: string }[];
      };
      for (const invite of data.invites ?? []) {
        await fetch(`/api/games/invites/${invite.invitation_id}/decline`, {
          method: "POST",
        });
      }
    }
    // And a solo attempt left open by an interrupted run.
    const active = await fetch("/api/games/sessions/active", { cache: "no-store" });
    if (active.ok) {
      const data = (await active.json()) as { session_id?: string | null };
      if (data.session_id) {
        await fetch(`/api/games/sessions/${data.session_id}/quit`, { method: "POST" });
      }
    }
  });
}

async function signIn(page: Page, learner: { code: string }): Promise<void> {
  const { code } = learner;
  await page.goto("/login");
  await page.getByLabel("Student code").fill(code);
  const pin = page.getByLabel(/PIN digit/);
  for (const [index, digit] of [...PIN].entries()) {
    await pin.nth(index).fill(digit);
  }
  await page.getByRole("button", { name: /play!/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  await clearLeftovers(page);
}

test("a learner signs in and lands on the dashboard", async ({ page }) => {
  await signIn(page, AMARA);

  // The shell is there, which is what every other screen depends on.
  await expect(page.getByRole("link", { name: "Games Hub" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Welcome back");
});

test("a solo game can be played to its end and restarted", async ({ page }) => {
  await signIn(page, AMARA);
  await page.goto("/games/number_guess");

  await page.getByRole("button", { name: /Easy/ }).click();
  await expect(page.getByText("Tap a number.")).toBeVisible();

  // Five numbers, skipped one at a time: the shortest honest path through a
  // real game, using the button a stuck learner would use.
  for (let round = 0; round < 5; round += 1) {
    const skip = page.getByRole("button", { name: "Show me the number" });
    await expect(skip).toBeEnabled();
    await Promise.all([
      page.waitForResponse(
        (response) => response.url().includes("/actions") && response.status() === 200,
      ),
      skip.click(),
    ]);
  }

  await expect(page.getByText(/You got \d+ of 5 numbers\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Play again" })).toBeVisible();
});

test("two learners meet in Checkers and one resigns", async ({ browser }) => {
  // Two browsers, dev-server compilation and sockets: give it room.
  test.setTimeout(120_000);
  const amaraContext = await browser.newContext();
  const bayoContext = await browser.newContext();
  const amara = await amaraContext.newPage();
  const bayo = await bayoContext.newPage();

  try {
    await signIn(amara, AMARA);
    await signIn(bayo, BAYO);

    // Amara opens a lobby by tapping Bayo on the roster.
    await amara.goto("/games/checkers");
  await amara.getByRole("button", { name: `Invite ${BAYO.name}` }).click();
  await amara.waitForURL(/\/games\/checkers\/[0-9a-f-]+$/);
  await expect(amara.getByText(`Waiting for ${BAYO.name} to join.`)).toBeVisible();

    // Bayo takes the seat from his inbox.
    await bayo.goto("/games/invites");
    await expect(
      bayo.getByText(`${AMARA.name} wants to play Checkers with you.`).first(),
    ).toBeVisible();
    await bayo.getByRole("button", { name: "Play" }).first().click();
    await bayo.waitForURL(/\/games\/checkers\/[0-9a-f-]+$/);
    await expect(bayo.getByRole("grid", { name: "Checkers board" })).toBeVisible();

    // Both sockets are up, so the match is being played and resign is legal.
    await expect(amara.getByRole("button", { name: "Resign" })).toBeEnabled();

    await amara.getByRole("button", { name: "Resign" }).click();
    await amara.getByRole("button", { name: "Yes, resign" }).click();

    await expect(amara.getByRole("button", { name: "Play again" })).toBeVisible();
    await expect(bayo.getByText("You won.")).toBeVisible();
  } finally {
    await amaraContext.close();
    await bayoContext.close();
  }
});
