/**
 * The three faces the design uses, self-hosted.
 *
 * These are the OFL woff2 files from Google Fonts, committed under `web/fonts`
 * and loaded with `next/font/local`. The reason is practical: `next/font/google`
 * reaches out at build time (and this Next version's manifest does not know
 * Atkinson Hyperlegible Next at all), while a school laptop should never wait
 * on fonts.googleapis.com to read a sentence.
 *
 * - Plus Jakarta Sans: headings, buttons, numbers that ring up fast.
 * - Atkinson Hyperlegible Next: body text. Built for readers who confuse b/d
 *   and p/q, which is a real share of our 8–13 band.
 * - JetBrains Mono: student codes and PINs, where 0/O and 1/l must not blur.
 *
 * Each file is the latin variable face, so one file covers every weight used.
 */

import localFont from "next/font/local";

export const headlineFont = localFont({
  src: [{ path: "../fonts/plus-jakarta-sans-latin.woff2", weight: "600 800", style: "normal" }],
  variable: "--font-jakarta",
  display: "swap",
  fallback: ["system-ui", "Segoe UI", "sans-serif"],
});

export const bodyFont = localFont({
  src: [
    {
      path: "../fonts/atkinson-hyperlegible-next-latin.woff2",
      weight: "400 700",
      style: "normal",
    },
  ],
  variable: "--font-atkinson",
  display: "swap",
  fallback: ["system-ui", "Segoe UI", "sans-serif"],
});

export const monoFont = localFont({
  src: [{ path: "../fonts/jetbrains-mono-latin.woff2", weight: "500 700", style: "normal" }],
  variable: "--font-jetbrains",
  display: "swap",
  fallback: ["ui-monospace", "Consolas", "monospace"],
});

export const fontVariables = `${headlineFont.variable} ${bodyFont.variable} ${monoFont.variable}`;
