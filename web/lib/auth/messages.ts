/**
 * One fixed sentence per server reason (Appendix D.5).
 *
 * A learner never sees a raw code, a stack trace, or a sentence assembled from
 * parts. Every branch below is written to be read aloud to a child, so each is
 * at most eight words and carries exactly one idea.
 */

const BY_CODE: Record<string, string> = {
  // `invalid_credentials` is a failed sign-in; `unauthenticated` is a session
  // that has gone. They must never share a sentence, or a child who mistyped
  // their password is told to do something they are already looking at.
  invalid_credentials: "That code or PIN is not right.",
  unauthenticated: "Please sign in again.",
  forbidden: "You cannot open this page.",
  not_found: "We could not find that.",
  rate_limited: "Too many tries. Wait a moment.",
  validation_error: "Please check what you typed.",
  conflict: "That did not work. Try again.",
  unavailable: "The server is resting. Try later.",
  internal_error: "Something went wrong. Please try again.",
  bad_request: "Please check what you typed.",
};

/**
 * The sentence to show for a failed request.
 *
 * `status` is used only when the server sent no usable code, so the message
 * still makes sense if the API is unreachable.
 */
export function sentenceFor(code: string | undefined, status?: number): string {
  if (code && BY_CODE[code]) return BY_CODE[code];
  if (status === 401) return "Please sign in again.";
  if (status === 403) return "You cannot open this page.";
  if (status === 404) return "We could not find that.";
  if (status === 429) return "Too many tries. Wait a moment.";
  if (status && status >= 500) return "The server is resting. Try later.";
  return "Something went wrong. Please try again.";
}
