/**
 * Shapes returned by the identity endpoints (P1-T05).
 *
 * These mirror `api/app/identity/schemas.py`. `npm run gen:api` emits the full
 * generated union in `lib/api/schema.ts`, but the pages only ever touch these
 * six fields, so a small explicit type keeps the components readable.
 */

/**
 * Three roles (D-37, api/app/identity/models.py).
 *
 * There is no platform role: making a school is a command on the server. Content
 * work belongs to staff, so a coach writes words and a coach's own words may go
 * live (D-38).
 */
export type Role = "learner" | "coach" | "school_admin";

export type School = {
  id: string;
  name: string;
  timezone: string;
  leaderboards_enabled: boolean;
};

export type AgeBand = { id: string; label: string };

/** The caller's own account. Only ever about themselves. */
export type SelfProfile = {
  id: string;
  preferred_name: string;
  real_name: string;
  avatar_key: string;
  role: Role;
  status: string;
  school_id: string;
  date_of_birth: string;
};

export type Me = {
  user: SelfProfile;
  school: School;
  age_band: AgeBand | null;
};

/** Everything another learner may see (P1-T05). Two fields and an id. */
export type PublicProfile = {
  id: string;
  preferred_name: string;
  avatar_key: string;
};

export type ClassSummary = {
  id: string;
  name: string;
  grade: number | null;
};

export type ClassMembers = {
  class: ClassSummary;
  members: PublicProfile[];
};
