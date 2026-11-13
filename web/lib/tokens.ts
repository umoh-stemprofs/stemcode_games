/**
 * Design tokens (P0-T06).
 *
 * Restyling should never require touching components, so colours, spacing,
 * radii, and type sizes live here and are mirrored as CSS variables in
 * globals.css.
 *
 * The sizes below are the Appendix D minimums, not aspirations:
 *   - body text >= 20px, never below 16px
 *   - touch/click target >= 56x56px
 * These are the defaults. A component that needs to go below them needs a
 * design decision, not a local override.
 */

export const colors = {
  ink: "#111827",
  inkMuted: "#4b5563",
  surface: "#ffffff",
  surfaceMuted: "#f3f4f6",
  border: "#d1d5db",
  brand: "#1d4ed8",
  brandContrast: "#ffffff",
  success: "#15803d",
  warning: "#b45309",
  danger: "#b91c1c",
  focus: "#1d4ed8",
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
  sm: "6px",
  md: "10px",
  lg: "16px",
  pill: "999px",
} as const;

/** Appendix D.1: body text 20px, never below 16px. */
export const fontSize = {
  body: "20px",
  bodyMin: "16px",
  large: "24px",
  heading: "32px",
  display: "44px",
} as const;

/** Appendix D.1: 56x56px minimum, 8px apart. */
export const touch = {
  minTarget: "56px",
  minGap: "8px",
} as const;

export const tokens = { colors, space, radius, fontSize, touch } as const;
export type Tokens = typeof tokens;
