"use client";

/**
 * The "no access" content, in one place.
 *
 * Used by the `/no-access` route and rendered inline when a page can tell from
 * the role alone that the screen is not for this person. One sentence, one
 * reason, one way forward — never a stack trace, never a raw code.
 */

import { Icon } from "@/components/icons";
import { ButtonLink, Card } from "@/components/ui";

export function NoAccess() {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-5">
      <Card className="flex flex-col items-center gap-3 p-6 text-center sm:p-8">
        <span
          aria-hidden="true"
          className="grid size-14 place-items-center rounded-2xl bg-sun-soft text-sun-ink"
        >
          <Icon name="lock" size={28} />
        </span>
        <h1 className="font-headline text-[clamp(26px,5vw,34px)] font-extrabold leading-tight text-ink">
          You cannot open this page.
        </h1>
        <p className="text-body text-ink-muted">This page is not for you.</p>
        <p className="text-body-min text-ink-muted">Ask your Coach if you think this is wrong.</p>
        <ButtonLink href="/" arrow className="mt-2 w-full sm:w-fit">
          Go back home
        </ButtonLink>
      </Card>
    </div>
  );
}
