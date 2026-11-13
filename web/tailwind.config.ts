import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "var(--color-ink)",
        "ink-muted": "var(--color-ink-muted)",
        surface: "var(--color-surface)",
        "surface-muted": "var(--color-surface-muted)",
        border: "var(--color-border)",
        brand: "var(--color-brand)",
        "brand-contrast": "var(--color-brand-contrast)",
      },
      fontSize: {
        // Appendix D: 20px body, 16px absolute floor.
        body: ["20px", { lineHeight: "1.5" }],
        "body-min": ["16px", { lineHeight: "1.5" }],
        large: ["24px", { lineHeight: "1.4" }],
        heading: ["32px", { lineHeight: "1.25" }],
        display: ["44px", { lineHeight: "1.15" }],
      },
      minHeight: {
        target: "var(--touch-target)",
      },
      minWidth: {
        target: "var(--touch-target)",
      },
      borderRadius: {
        md: "10px",
        lg: "16px",
      },
    },
  },
  plugins: [],
};

export default config;
