/**
 * One way to say yes to an invitation (P7-T07).
 *
 * Shared by the inbox and the popup so both do the same three things in the
 * same order: accept, start the challenge when it is not a live match, then
 * hand back the path the learner should open. A live seat is already the match
 * and has no parent to start, which is the bug that used to leave this screen
 * stuck on a 404.
 */

import { apiFetch } from "@/lib/api/client";
import type { InviteAccepted } from "@/lib/games/social";
import { seatPath } from "@/lib/games/social";

export async function acceptInvite(invitationId: string): Promise<string> {
  const accepted = await apiFetch<InviteAccepted>("/api/games/invites/accept", {
    method: "POST",
    body: JSON.stringify({ invitation_id: invitationId }),
  });
  if (!accepted.live) {
    await apiFetch(`/api/games/challenges/${accepted.parent_id}/start`, { method: "POST" });
  }
  return seatPath(accepted);
}
