/**
 * Design tokens (P0-T06, restyled in P11).
 *
 * Restyling should never require touching components, so colours, spacing,
 * radii, type sizes and depth live here and are mirrored as CSS variables in
 * `globals.css` and as Tailwind theme values in `tailwind.config.ts`.
 *
 * The sizes below are the Appendix D minimums, not aspirations:
 *   - body text >= 20px, never below 16px
 *   - touch/click target >= 56x56px
 * These are the defaults. A component that needs to go below them needs a
 * design decision, not a local override.
 *
 * The palette is the "ClearSTEM" minimalist system: an off-white canvas, white
 * cards with a crisp 1.5px edge, one electric cobalt for anything you can press
 * and three accents that belong to the three games (green for Number Guess,
 * violet for Word Scramble, cobalt for Checkers). Nothing else is coloured
 * without a reason, because visual noise is a reading cost.
 */

export const colors = {
  /** Page background. */
  canvas: "#f8fafd",
  /** Cards and sheets. */
  surface: "#ffffff",
  /** Tinted inner tiles and selected rows. */
  surfaceMuted: "#f0f3ff",
  surfaceSunk: "#e7eeff",
  ink: "#111c2d",
  inkMuted: "#434656",
  border: "#e2e8f0",
  borderStrong: "#0f172a",
  brand: "#0d5bff",
  brandDeep: "#0045cc",
  brandSoft: "#dce1ff",
  brandContrast: "#ffffff",
  success: "#006c47",
  successSoft: "#d9f7e9",
  /** Attention and rewards: XP, streaks, hints. */
  sun: "#ff8b00",
  sunSoft: "#fff6ee",
  sunInk: "#8a4a00",
  danger: "#dc2626",
  dangerSoft: "#ffe4e2",
  violet: "#5856d6",
  violetSoft: "#e0e7ff",
  focus: "#facc15",
} as const;

/** Alias kept for the older semantic names that still appear in copy. */
export const semantic = {
  warning: colors.sunInk,
} as const;

export const fontFamily = {
  headline: "var(--font-jakarta)",
  body: "var(--font-atkinson)",
  mono: "var(--font-jetbrains)",
} as const;

export const space = {
  xs: "4px",
  sm: "8px",
  md: "16px",
  lg: "24px",
  xl: "32px",
  xxl: "48px",
} as const;

export const radius = {
  sm: "8px",
  md: "12px",
  tile: "16px",
  card: "24px",
  pill: "999px",
} as const;

/** Appendix D.1: body text 20px, never below 16px. */
export const fontSize = {
  body: "20px",
  bodyMin: "16px",
  large: "22px",
  heading: "32px",
  display: "40px",
} as const;

/** Appendix D.1: 56x56px minimum, 8px apart. */
export const touch = {
  minTarget: "56px",
  minGap: "8px",
} as const;

/**
 * Depth without blur. A card sits on the canvas with one hairline shadow; a
 * pressable control gets a 2–3px solid lip instead of a glow, so a child can
 * see that it moves.
 */
export const shadow = {
  card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 18px 40px -28px rgba(15, 23, 42, 0.28)",
  tile: "inset 0 1px 0 rgba(15, 23, 42, 0.03)",
  primary: "0 2px 0 0 #0045cc",
  success: "0 2px 0 0 #005235",
  violet: "0 2px 0 0 #4745b8",
} as const;

export const tokens = { colors, fontFamily, space, radius, fontSize, touch, shadow } as const;
export type Tokens = typeof tokens;
