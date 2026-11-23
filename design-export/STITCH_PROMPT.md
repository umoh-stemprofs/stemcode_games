# Prompt for Google Stitch

Send this **once**, with no files attached. It sets the language.

Then send one screen per message: one image from `design-export/screens/`, the control card from
[SCREENS.md](SCREENS.md), and *"Redesign this screen only, following the brief."* Start with sign
in, home, and the Word Scramble round — iterate those until the look is right, because they define
what every later screen inherits.

--- COPY FROM HERE ---

You are redesigning an existing school web app called **STEM Games**. This is a full visual
overhaul: new palette, typography, spacing, depth, card design, navigation, iconography, and
loading/empty/error states. The information architecture, the screens and every control stay
exactly as they are. You are changing how it looks and feels, not what it does.

This message is the brief and the design system, not a whole app in one pass. I will send you the
screens one at a time as images. Each image is the **current state** of one real screen from the
running product, not the target: keep its structure, its elements, their order, its labels and its
copy, and change only how it looks.

Everything must be able to sit next to the screens I have not sent yet, so build one small,
reusable set of tokens and components rather than a one-off page per screen.

When you do get an image, read it as markup: ignore anything that is obviously a browser overlay or
a dev badge in the corner.

## Who uses it

- **Learners, aged 8–13**, in classrooms in Nigeria. Many read below their grade level, some cannot
  yet read a sentence. They play on school laptops and low-end Android tablets, often on slow Wi-Fi,
  sometimes with one hand while standing.
- **Coaches** (teachers) set time limits and write the word content.
- **School admins** do everything a coach does plus blocked words and reports.

So the same product has to feel like a game to a child and like a trustworthy tool to a teacher.

## Hard rules — these are product requirements, not taste

1. **Body text 20px, never below 16px.** Line height 1.5. No screen may use a smaller size for
   anything a person has to read.
2. **Every tappable thing is at least 56×56px, with at least 8px between targets.** No exceptions
   for "secondary" actions, links, tabs, dialog buttons or board squares.
3. **One decision per screen.** If a screen currently has two decisions, do not add a third.
4. **Plain language.** Sentences of 8 words or fewer, and no more than 25 words of interface text
   on a learner screen. **Keep the existing copy verbatim** wherever it already fits. If a label
   genuinely must change, keep it to 1–2 words and give me an old → new list at the end.
5. **Never show a countdown number or a ticking clock.** Time is a filling bar or a sentence.
   The only numbers a learner reads are the ones that are part of the game.
6. **No read-aloud, speaker, or voice button.** There is deliberately no audio feature. Do not add
   one, and do not design one.
7. **No badges, unread counts, streaks, points pop-ups, confetti storms, or anything that nags.**
   This app is designed not to create anxiety.
8. **Never add, remove, merge, or hide a control, field, tab, or screen.** Every button in the
   source keeps its job and its label. If you believe something should move or go, write it in the
   notes — do not do it.
9. **Never rely on colour alone** to carry meaning. Checkers pieces, "you can move here" markers,
   correct/wrong feedback, and selected tabs each need a second cue: a shape, a ring, a label, a
   pattern.
10. **Accessibility:** 4.5:1 contrast for text, 3:1 for large text and for control borders and
    icons; a visible 3px focus ring on everything focusable; full keyboard operation; no horizontal
    scrolling at 390px wide; nothing breaks at 200% text zoom; honour `prefers-reduced-motion`.
11. **Mobile first.** 390px wide is the primary canvas, single column. Desktop is the same design
    with more air, not a different design.

## What it looks like now, and what it should be

Right now it is flat Tailwind defaults: a blue `#1d4ed8` primary, white cards on grey, 10px
corners, one 32px heading, and a lot of text stacked in boxes. It reads like an admin tool that
happens to contain a game.

Make it feel like a **friendly, confident classroom**: warm, calm, tactile, and clearly made for
children, without becoming babyish or cluttered for the staff screens.

- **Type:** a geometric or humanist sans with a tall x-height and very legible numerals. Set a
  clear scale (page title, card title, body, small) and stick to it — no ad-hoc sizes.
- **Colour:** one primary brand accent; a background that is a soft tint rather than pure grey; and
  **three secondary accents used only as small highlights**, one per game (Word Scramble, Number
  Guess, Checkers). Keep success, warning and danger reserved for state, never decoration. Give me
  hex values that pass the contrast rules against their backgrounds.
- **Shape and depth:** 12–16px card radius, pill for chips and avatar buttons, at most two
  elevation levels, and buttons that look and feel pressable (a real pressed state, not just a
  colour change).
- **Space:** generous. A learner screen should look like it has room to breathe, and the one action
  should be obvious from across a classroom.
- **Illustration and icons:** replace the emoji stand-ins with simple, bold, single-colour
  pictograms at a consistent weight: a chequered board, three loose letter tiles, an up/down arrow,
  a clock, an avatar fallback. Every interactive element with an icon also keeps its text label.
- **Game screens are the showpiece.** The letter tray, the number pad and the board are the three
  most important pieces of UI in the product; design them as objects a child wants to touch.
  The board must stay an 8×8 grid of 56px minimum squares that scrolls inside its own box rather
  than pushing the page wide.
- **Staff screens** can be denser and more neutral, but never below 16px text or 56px targets, and
  they use the same components as everywhere else.

Do **not** design: dark mode, a settings page, a profile page, search, onboarding tours, a logo
redesign, marketing pages, or any new game.

## The frame: header and dialogs

Every signed-in screen sits inside the same shell: product name, a role-dependent menu, the time
meter (learners, not on Home), the XP chip (learners), the avatar and preferred name, and
`Sign out`. The three menus are fixed:

- Learner: Home, Play, Invites, Boards, My class
- Coach: Home, Classes, Time limits, Words, Boards, XP
- School admin: Home, Classes, Time limits, Words, Blocked words, Reports, Boards, XP

Design the header for three cases: 390px (this is the hardest part — it currently clips), 768px,
and 1280px. Consider a compact two-row header on mobile rather than squeezing. Also design the
"Leave this game?" dialog and the small "just a moment" loading state.

## ONE SCREEN AT A TIME

This message is the brief and the design system, not the whole app. When I send you a screen, that
is the only screen to redesign: keep every control on it, keep the copy, and show the states it
really has — the loading line, the empty state, the error state, and disabled buttons. Never add a
control that is not in the image, and never merge two into one.

On this first message, give me the tokens stylesheet and the component sheet described below, so
every later screen starts from the same parts.

## WHAT TO GIVE ME BACK

**From this first message** — the system, not screens:

1. **A tokens stylesheet** — one `:root` block of CSS custom properties, using exactly these names
   because the app already reads them:
   `--color-ink`, `--color-ink-muted`, `--color-surface`, `--color-surface-muted`,
   `--color-border`, `--color-brand`, `--color-brand-contrast`, `--color-success`,
   `--color-warning`, `--color-danger`, `--color-focus`, plus `--radius-sm|md|lg|pill`,
   `--space-xs|sm|md|lg|xl|xxl`, `--font-body|body-min|large|heading|display`,
   `--touch-target`, `--touch-gap`, and any shadow scale you introduce.
2. **A component sheet** showing each piece in every state: button (primary, secondary, danger,
   ghost, disabled), text input, select, checkbox, card, list row, chip, progress bar, header (the
   three role menus listed above), dialog, avatar button, letter tile (in tray, placed, take-back),
   number-pad key, checkers square (light, dark, selected, legal move, forced jump), leaderboard
   row, data table, empty state, loading state, error state.

**From each screen message after that** — one page of plain semantic HTML plus CSS, using those
same tokens and components: no framework, no build step, no external CSS or images. It must hold at
390px and at 1280px. Name the classes clearly enough that I can map them to React components. End
with a two-line note: anything you could not fit, and anything that looks like it would confuse a
child.

## LABELS

Keep every label exactly as written. If a label genuinely cannot fit the new design, change it and
list it as old → new at the end of that screen's message. Do not quietly reword.

--- END OF PROMPT ---

## Per-screen message

After the brief and the system come back, send each screen on its own: the image, the card, and

> Redesign this screen only, following the brief. This is `<name>` — `<one line on what the screen
> is for>`. Keep every control listed on the card, keep the copy exactly, and show its loading,
> empty and disabled states. Here is the control card: `<paste the matching card from
> SCREENS.md>`.

## When the designs come back

Hand the files to me rather than editing `web/` yourself. The mapping is mechanical but has three
rules that matter: the palette goes into `web/lib/tokens.ts` **and** `web/app/globals.css` (never a
local override), the 56px/20px minimums are re-verified on the real pages, and no screen may lose a
server sentence. Any redesign also has to re-pass Appendix D in
[GAMES_BUILD_PLAN.md](../GAMES_BUILD_PLAN.md#L749), including the D.5 first-session walkthrough.
