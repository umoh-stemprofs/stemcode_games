import type { Config } from "tailwindcss";

/**
 * The theme is a projection of `lib/tokens.ts`. Every colour, size and radius a
 * component uses should come from here (or from a primitive in
 * `components/ui.tsx`), never from a hex value in a page.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--color-canvas)",
        surface: "var(--color-surface)",
        "surface-muted": "var(--color-surface-muted)",
        "surface-sunk": "var(--color-surface-sunk)",
        ink: "var(--color-ink)",
        "ink-muted": "var(--color-ink-muted)",
        line: "var(--color-border)",
        "line-strong": "var(--color-border-strong)",
        brand: "var(--color-brand)",
        "brand-deep": "var(--color-brand-deep)",
        "brand-soft": "var(--color-brand-soft)",
        "brand-contrast": "var(--color-brand-contrast)",
        ok: "var(--color-success)",
        "ok-soft": "var(--color-success-soft)",
        sun: "var(--color-sun)",
        "sun-soft": "var(--color-sun-soft)",
        "sun-ink": "var(--color-warning)",
        danger: "var(--color-danger)",
        "danger-soft": "var(--color-danger-soft)",
        violet: "var(--color-violet)",
        "violet-soft": "var(--color-violet-soft)",
        focus: "var(--color-focus)",
        // Older semantic aliases still used in a few pages.
        border: "var(--color-border)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
      },
      fontFamily: {
        headline: ["var(--font-jakarta)", "ui-sans-serif", "system-ui", "sans-serif"],
        body: ["var(--font-atkinson)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      fontSize: {
        // Appendix D: 20px body, 16px absolute floor.
        body: ["20px", { lineHeight: "1.5" }],
        "body-min": ["16px", { lineHeight: "1.5" }],
        large: ["22px", { lineHeight: "1.4" }],
        heading: ["32px", { lineHeight: "1.2" }],
        display: ["40px", { lineHeight: "1.1" }],
        label: ["14px", { lineHeight: "1.35" }],
        micro: ["12px", { lineHeight: "1.2", letterSpacing: "0.08em" }],
      },
      minHeight: {
        target: "var(--touch-target)",
      },
      minWidth: {
        target: "var(--touch-target)",
      },
      borderRadius: {
        md: "12px",
        lg: "24px",
        pill: "999px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 18px 40px -28px rgba(15, 23, 42, 0.28)",
        tile: "inset 0 1px 0 rgba(15, 23, 42, 0.03)",
        primary: "0 2px 0 0 #0045cc",
        success: "0 2px 0 0 #005235",
        violet: "0 2px 0 0 #4745b8",
      },
    },
  },
  plugins: [],
};

export default config;
