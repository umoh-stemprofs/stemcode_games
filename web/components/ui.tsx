/**
 * The design-system primitives.
 *
 * Pages compose these instead of repeating long class strings, so a change to
 * the card radius or the button height happens once. Everything here is a
 * projection of `lib/tokens.ts`; no component picks its own colour.
 *
 * Appendix D is encoded in the defaults: `Button size="md"` is 56px tall, body
 * copy is 20px, and nothing is hidden behind colour alone — every chip and
 * state carries words.
 */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";

/** Join class names, dropping the falsy ones. */
export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export const cardClass =
  "rounded-3xl border border-line bg-surface shadow-card";

export function Card({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & ComponentProps<"div">) {
  return (
    <div className={cx(cardClass, className)} {...rest}>
      {children}
    </div>
  );
}

/** A card header: icon tile, title, one sentence, optional action on the right. */
export function PageHeader({
  title,
  subtitle,
  icon,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: IconName;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-2">
        <h1 className="flex items-center gap-3 font-headline text-[clamp(26px,4.5vw,36px)] font-extrabold tracking-tight text-ink">
          {icon ? (
            <span
              aria-hidden="true"
              className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand-deep"
            >
              <Icon name={icon} size={22} />
            </span>
          ) : null}
          <span className="min-w-0">{title}</span>
        </h1>
        {subtitle ? <p className="text-body text-ink-muted">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

type Variant = "primary" | "success" | "violet" | "secondary" | "ghost" | "danger" | "quiet";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-white shadow-primary hover:bg-brand-deep",
  success: "bg-ok text-white shadow-success hover:brightness-110",
  violet: "bg-violet text-white shadow-violet hover:brightness-110",
  secondary: "border-2 border-line-strong bg-surface text-ink hover:bg-surface-muted",
  ghost: "border border-line bg-surface text-ink hover:bg-surface-muted",
  danger: "bg-danger text-white hover:brightness-110",
  quiet: "text-ink-muted hover:bg-surface-muted hover:text-ink",
};

const SIZES: Record<Size, string> = {
  sm: "min-h-[44px] gap-2 px-3.5 text-label",
  md: "min-h-target gap-2.5 px-5 text-[17px]",
  lg: "min-h-[64px] gap-3 px-6 text-[19px]",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", extra?: string) {
  return cx(
    "inline-flex items-center justify-center rounded-2xl font-headline font-bold leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    extra,
  );
}

type ButtonExtras = {
  variant?: Variant;
  size?: Size;
  /** Show a forward arrow after the label. */
  arrow?: boolean;
  icon?: IconName;
  className?: string;
};

export function Button({
  variant = "primary",
  size = "md",
  arrow = false,
  icon,
  className,
  children,
  ...rest
}: ButtonExtras & ComponentProps<"button">) {
  return (
    <button type="button" className={buttonClass(variant, size, className)} {...rest}>
      {icon ? <Icon name={icon} size={size === "sm" ? 16 : 20} /> : null}
      <span>{children}</span>
      {arrow ? <Icon name="arrow-right" size={size === "sm" ? 16 : 20} /> : null}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  arrow = false,
  icon,
  className,
  children,
  ...rest
}: ButtonExtras & { href: string; children: ReactNode } & Omit<
    ComponentProps<typeof Link>,
    "href" | "className" | "children"
  >) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {icon ? <Icon name={icon} size={size === "sm" ? 16 : 20} /> : null}
      <span>{children}</span>
      {arrow ? <Icon name="arrow-right" size={size === "sm" ? 16 : 20} /> : null}
    </Link>
  );
}

const CHIP_TONES = {
  blue: "bg-brand-soft text-brand-deep",
  green: "bg-ok-soft text-ok",
  violet: "bg-violet-soft text-violet",
  sun: "bg-sun-soft text-sun-ink",
  neutral: "bg-surface-muted text-ink-muted",
} as const;

export function Chip({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof CHIP_TONES;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-label font-bold",
        CHIP_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A time or XP meter: the bar decorates a sentence, it never replaces one. */
export function Progress({
  value,
  label,
  tone = "brand",
  className,
}: {
  value: number;
  label: string;
  tone?: "brand" | "sun" | "danger";
  className?: string;
}) {
  const width = Math.max(2, Math.min(100, Math.round(value)));
  const fill =
    tone === "danger" ? "bg-danger" : tone === "sun" ? "bg-sun" : "bg-brand";
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={width}
      className={cx("h-2.5 w-full overflow-hidden rounded-pill bg-surface-sunk", className)}
    >
      <div className={cx("h-full rounded-pill transition-[width]", fill)} style={{ width: `${width}%` }} />
    </div>
  );
}

/** The calm version of "nothing here yet" — never an error, never a dead end. */
export function EmptyState({
  icon = "sparkles",
  title,
  children,
}: {
  icon?: IconName;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-line bg-surface-muted px-6 py-8 text-center">
      <span aria-hidden="true" className="grid size-12 place-items-center rounded-2xl bg-surface text-ink-muted">
        <Icon name={icon} size={22} />
      </span>
      <p className="font-headline text-large font-bold text-ink">{title}</p>
      {children ? <p className="text-body-min text-ink-muted">{children}</p> : null}
    </div>
  );
}

/** A loading line that does not shout. */
export function Loading({ children = "Just a moment." }: { children?: ReactNode }) {
  return (
    <p role="status" className="text-body text-ink-muted">
      {children}
    </p>
  );
}

/** One plain sentence when something went wrong. Never a code. */
export function Alert({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-2xl border border-line bg-danger-soft px-4 py-3 text-body-min font-semibold text-ink"
    >
      {children}
    </p>
  );
}
