/**
 * The icon set, in one place.
 *
 * Inline SVG rather than an icon font: a school laptop on a bad connection
 * should never see a word render as `arrow_forward`, and a ligature that fails
 * to load is worse than no icon at all.
 *
 * Icons are decorative by default. Anything whose meaning is not repeated by
 * nearby text takes an `aria-label` from the caller.
 */

import type { SVGProps } from "react";

const PATHS = {
  "arrow-right": "M5 12h14M13 6l6 6-6 6",
  "arrow-left": "M19 12H5M11 18l-6-6 6-6",
  "chevron-right": "M9 6l6 6-6 6",
  "chevron-left": "M15 6l-6 6 6 6",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  bolt: "M13 2.5L4.8 13.4h6.1l-1 8.1L19.4 10h-6.2l-.2-7.5z",
  trophy:
    "M8 21h8M12 17v4M7 4h10v4.5a5 5 0 01-10 0V4zM7 6.5H4V8a3 3 0 003 3M17 6.5h3V8a3 3 0 01-3 3",
  users:
    "M16 20v-1.5a4 4 0 00-4-4H6.5a4 4 0 00-4 4V20M9.2 3.6a3.6 3.6 0 100 7.2 3.6 3.6 0 000-7.2zM17 4.2a3.5 3.5 0 010 6.9M22 20v-1.5a4 4 0 00-3-3.8",
  "user-plus":
    "M15 20v-1.5a4 4 0 00-4-4H5.5a4 4 0 00-4 4V20M8.2 3.6a3.6 3.6 0 100 7.2 3.6 3.6 0 000-7.2zM18.5 7.5v6M21.5 10.5h-6",
  play: "M8 5.2v13.6L19 12 8 5.2z",
  grid: "M4 4h6.4v6.4H4zM13.6 4H20v6.4h-6.4zM4 13.6h6.4V20H4zM13.6 13.6H20V20h-6.4z",
  chart: "M3.5 20.5h17M6.5 20.5v-6M12 20.5V8M17.5 20.5v-9.5",
  book: "M4 19.2A2.2 2.2 0 016.2 17H20M6.2 2H20v20H6.2A2.2 2.2 0 014 19.8V4.2A2.2 2.2 0 016.2 2z",
  lock: "M5 10h14v11H5zM8 10V7a4 4 0 018 0v3",
  plus: "M12 5v14M5 12h14",
  check: "M4.5 12.5l5 5 10-10.5",
  close: "M6 6l12 12M18 6L6 18",
  target: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16.5a4.5 4.5 0 100-9 4.5 4.5 0 000 9zM12 13a1 1 0 100-2 1 1 0 000 2z",
  flame:
    "M12 2.5c3 4 6 6.3 6 10a6 6 0 11-12 0c0-2 1-3.6 2.4-5 .5 1.5 1.4 2.4 2.4 2.4.1-2.9.9-5.8 1.2-7.4z",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  "eye-off": "M3 3l18 18M10.6 6.1A9.7 9.7 0 0112 6c6 0 9.5 6 9.5 6a17 17 0 01-3.3 3.9M6.3 7.8C3.9 9.4 2.5 12 2.5 12S6 18 12 18c1 0 1.9-.2 2.8-.5",
  refresh: "M20 12a8 8 0 11-2.3-5.7M20 4.5v7h-7",
  star: "M12 3l2.8 5.9 6.2.8-4.5 4.4 1.1 6.4L12 17.6 6.4 20.5l1.1-6.4L3 9.7l6.2-.8L12 3z",
  sparkles:
    "M12 3l1.7 4.6L18.5 9l-4.8 1.4L12 15l-1.7-4.6L5.5 9l4.8-1.4L12 3zM18.5 14.5l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9.9-2.3z",
  message: "M20.5 11.5a7.5 7.5 0 01-7.5 7.5H7.5L3 21.5V12a7.5 7.5 0 017.5-7.5h2.5a7.5 7.5 0 017.5 7z",
  shield: "M12 3l8 3v5.5c0 4.8-3.4 8.2-8 9.5-4.6-1.3-8-4.7-8-9.5V6l8-3z",
  calendar: "M4 6.5h16V21H4zM8 2.5v5M16 2.5v5M4 11.5h16",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14zM20.5 20.5L16 16",
  list: "M8.5 6H21M8.5 12H21M8.5 18H21M3.5 6h.01M3.5 12h.01M3.5 18h.01",
  edit: "M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z",
  trash: "M3.5 6.5h17M8.5 6.5v-2h7v2M6 6.5l1 14h10l1-14",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 16.5l4.5-4.5L16 7.5M20.5 12H9",
  flag: "M4.5 21V3.5M4.5 4h11l-2 3.5 2 3.5h-11",
  link: "M10.5 13.5a5 5 0 007 0l1.8-1.8a5 5 0 00-7-7l-.9.9M13.5 10.5a5 5 0 00-7 0l-1.8 1.8a5 5 0 007 7l.9-.9",
  hourglass: "M6.5 2.5h11M6.5 21.5h11M6.5 2.5c0 5 5.5 6 5.5 9.5s-5.5 4.5-5.5 9.5M17.5 2.5c0 5-5.5 6-5.5 9.5s5.5 4.5 5.5 9.5",
  layers: "M12 3l9 4.5-9 4.5-9-4.5L12 3zM3 12l9 4.5 9-4.5M3 16.5L12 21l9-4.5",
  key: "M14.5 9.5a4.5 4.5 0 10-4.1 4.5L9 15.5H7v2H5v2H2.5v-3l7.9-7.9a4.5 4.5 0 014.1-2.1z",
  badge: "M12 3l8.5 4v6.5c0 4-3.6 6.7-8.5 7.5-4.9-.8-8.5-3.5-8.5-7.5V7L12 3zM8.5 11.5l2.5 2.5 4.5-4.5",
} as const;

export type IconName = keyof typeof PATHS;

type Props = SVGProps<SVGSVGElement> & {
  name: IconName;
  /** Rendered size in pixels; 20 in text, 24 in a control. */
  size?: number;
};

export function Icon({ name, size = 20, className, ...rest }: Props) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
