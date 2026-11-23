# Screen packets for Google Stitch

Do not upload the app. Stitch gets **one screen per message**: one image, one short card. The image
is the current state; the card says what the screen is for and which controls must survive.

Three waves, in this order:

1. **The brief, once** — [STITCH_PROMPT.md](STITCH_PROMPT.md), no files attached.
2. **The language, three screens** — sign in, home, Word Scramble round. Iterate these until the
   look is right; they define the palette, type scale, button shape and card style for everything
   else.
3. **The rest, one at a time** — attach the screen's image, paste its card, say
   *"Redesign this screen only, following the brief. Keep every control."*

Sending twenty-four `.tsx` files in one go is the thing to avoid: Stitch redesigns the whole app in
one pass, invents consistency it cannot see, and silently drops the controls it did not notice.

## Screens already captured

Images live in `design-export/screens/`, at 1440 px wide, taken from the running app after the
minimalist redesign. The `Freebuff` pill in the top-left corner is the browser panel's own badge,
not part of the app — tell Stitch to ignore it.

| Screen | Image | Purpose |
|---|---|---|
| Sign in | `00-sign-in.png` | The first screen a child meets |
| Home | `01-home-learner.png` | Streak, time left, the three games, today's quest |
| Games hub | `02-games-hub.png` | Pick a game |
| Level picker | `03-level-picker.png` | Pick easy, medium or hard |
| Word Scramble round | `04-word-scramble-round.png` | Build the word from letters |
| Number Guess round | `05-number-guess-round.png` | Guess the number, narrowing |
| Boards | `06-boards.png` | The leaderboard, podium and the rest |
| Invites inbox | `07-invites-inbox.png` | One sentence per invite, two buttons |
| Classes | `08-classes.png` | One row per class |
| Checkers lobby | `09-checkers-lobby.png` | Pick an opponent |
| Class roster | `10-class-roster.png` | Who is in the class |
| Me (profile) | `11-me-profile.png` | Streak, level, quest, badges |
| Me (badges) | `12-me-badges.png` | The badge collection and best scores |
| Join with a friend | `13-join-with-friend.png` | Type a code |
| Words (staff) | `14-staff-words.png` | Word lists, age group, live/draft |
| Time limits (staff) | `15-staff-time-limits.png` | One card per class |
| Reports (staff) | `16-staff-reports.png` | The report queue |
| XP (staff) | `17-staff-xp.png` | Per-class XP by game |
| Blocked words (staff) | `18-staff-blocked-words.png` | Block a word, see the list |
| Game over | *not captured — needs ten rounds* | The result, XP, and the report route |
| Invite sheet | *not captured* | Invite a classmate, or show a code |
| Checkers match | *not captured — needs two tabs* | The board, clocks, draw and resign |
| No access | *not captured* | One sentence and a way home |

Staff screens reuse the same components as the learner pages, so they should be restyled from the
learner language rather than designed separately.

## Cards

Paste the matching card under the image. Every line is a control that exists today: restyle or
relocate it, never delete it or change its job.

**Sign in** — student code field; PIN field; `Sign in`; inline error sentence; the two help lines
(`It looks like A-1001.`, `Four numbers.`); `Ask your Coach if you cannot sign in.`

**Home** — greeting with preferred name; the streak capsule (`STREAK` / `Start today` or `N days`);
the three game cards with picture mark, name, one-line summary and `Play`; `All 3 games`;
today's quest card (title, goal sentence, progress bar, `N of 2`, `+10 XP`); the time-left pill in
the header; the XP pill; the avatar (opens Me) and `Sign out`.

**Games hub** — one card per game with a picture mark, name, one-line summary and `Play`; a
"Your turn" card with `Play my turn` when a challenge is owed; `My invites`; `Type a code`;
the "you cannot play right now" card with the reason sentence and a resume link.

**Level picker** — `Easy` / `Medium` / `Hard` (stars, and the 1–50 / 1–200 / 1–1,000 range on
Number Guess); `Play with a friend`; `← All games`.

**Word Scramble round** — the instruction line `Tap the letters.`; clue text and/or picture; the
placed-word area (each tile is tappable to take it back, marked with `×`); the letter tray (56px
tiles); `Done`; `Take a letter (−3)`; `I don't know`; `N tries left.`; the server's feedback
sentence; the ten round dots (filled as rounds finish); the round clock bar. There is deliberately
no "Word 3 of 10" counter and no running score.

**Number Guess round** — the window (`1–50` narrowing), the big number, `−` / `+` stepper,
12-key pad `1`–`9`, `0`, `⌫`, `✓`; the ↑/↓ feedback with the server's sentence
(`Too low. Go up.`); the pip row; the round clock bar.

**Game over** — `You got N of 10 words/numbers.`; the closing sentence; the score line; the XP line
(`+14 XP`, `3 of 50 today.`); the challenge comparison; `Report` → `What happened?` with its four
reason buttons and `Never mind`; `Thank you. A grown-up will look at this.`; `Play again`;
`All games`.

**Invite sheet** — `Play with a friend`; the classmate avatar buttons; `Show a code instead`;
the big code; the expiry sentence; `Play my turn`; `Copy link` / `Link copied`.

**Invites inbox** — one sentence per item; `Play`; `No thanks`; the empty state
`There is nothing here yet.`

**Join with a friend** — the code field (placeholder `ABCD EFGH`, two groups of four); `Join`
(disabled until eight characters); the error sentence; `Ask your Coach if the code does not
work.`

**Checkers lobby** — a classmate button per friend (disabled with a one-line reason when they are
not free); `Type a code instead`; `Back to games`.

**Checkers match** — the 8×8 board (56px squares, ringed movable pieces, legal-move markers,
forced-jump highlight); both player rows, each with a clock bar and an `MM:SS left` figure; the turn
sentence (`Your turn. Tap a piece.`, `Tap the piece. You must jump!`, `You are offline. We are
getting you back in.`); `Draw`; `Resign` → `Stop the match? You will lose it.` with `Yes, resign` /
`Keep playing`; a received draw offer with `Accept` / `No thanks`; `If the bar empties, you lose.`;
the result block with `Play again` and `Back to games`.

**Classes / roster** — one row per class with a chevron; the member count sentence; the avatar grid.

**Me** — preferred name and avatar; the streak capsule; `Level N` / `XP in all` / badge count chips;
the level bar (`0 of 100 XP`, `100 XP to level 2.`); today's quest; the badge grid (earned in
colour, locked greyed with a one-line how-to) and `Next: <badge>`; `Your bests`.

**Boards** — period tabs (Today / This week / This term / All time, plus This month when the school
enables it; All time is admin-only and This term is hidden when the school has no dates); `Game`
and `Class` selects for staff; the ranked rows (avatar, preferred name, XP); `You are number N.`;
the eligibility note (`Play N games to get on this board.`); the admin "Add your term dates" form
(name, first day, last day, `Save the term`) and the saved-terms list.

**No access** — `You cannot open this page.`; `This page is not for you.`; the ask-your-Coach line;
`Go back home`.

**Time limits** — the class list; `Set time for the whole class`; per-learner `Change` and
`Pause games`; the limit panel (minutes + reason + save/cancel); the pause panel (start/end +
reason + save/cancel); the "Recent changes" list.

**Words** — `Start a new word list` (age group select, "start with live words" checkbox,
`Make the list`); the list rows with live/draft/total counts and a status chip; on one list: the
status header, per-word rows (scrambled → answer, level, clue, status, first problem),
`Make it live`, `Take it down`, `Remove`, the bulk `Make the ready words live`; `Add a word`
(word, clue, level, `Add it`); `Add many words at once` (textarea + `Add these words` + the
per-line error report).

**Blocked words** — the word field; `Block this word`; the list with `Remove` per word; the
confirmation and error sentences.

**Reports** — one card per report: reported name, reason sentence, reporter, optional note.

**XP** — class select; period tabs; the XP table; the "no term dates" sentence.

## If Stitch asks for code instead of a picture

Give it the one file for that screen, never the folder: `web/app/<route>/page.tsx`. The control card
above is still what you hold it to, because the file alone does not show the loading, empty, error
or disabled states.

## Why not the whole app at once

Three reasons, all practical:

- Stitch designs what it can see. Twenty-four files in one prompt is a summary, and the summary
  drops the parts that make the screens work (disabled reasons, empty states, server sentences).
- Consistency comes from the first three screens, not from batching. Lock the language, then every
  later screen inherits it.
- A redesign that loses one control is a bug that reaches a child. One screen per message makes the
  loss visible immediately, against a card that names every control.
