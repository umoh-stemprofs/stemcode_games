# STEM Code V2 Games and Gamification

**Status:** Confirmed product direction  
**Last updated:** 3 November 2026

## 1. Goals

Games should increase healthy daily engagement, reasoning, problem-solving, and
curriculum reinforcement without displacing learning or distorting formal
academic progress.

## 2. Game catalog

Confirmed initial target catalog:

- Chess
- Checkers
- Original falling-block puzzle
- Word Scramble
- Guessing Game

Proposed first-release order:

1. Word Scramble
2. Guessing Game
3. Checkers
4. Chess
5. Falling-block puzzle

The first two validate content operations, sessions, limits, XP, offline play,
and leaderboards before live deterministic board games add matchmaking and move
validation.

## 3. Domain model

```text
games
game_versions
game_content_packs
game_sessions
game_participants
game_moves
game_results
game_invitations
game_access_policies
game_lockouts
game_xp_ledger
leaderboard_periods
leaderboard_entries
```

Scores and results are append-only. Leaderboards are derived projections, not
client-writable totals.

## 4. Game access and time

- A platform default defines daily active play time.
- A school may adopt a stricter default.
- A coach may override the limit for an assigned class or student.
- A coach may impose a temporary lockout with a reason and expiry.
- Menus, loading time, and disconnected idle time do not count as active play.
- The server is authoritative for competitive eligibility and time allowance.
- Offline play records local active time and reconciles it before allowing more
  competitive play online.

## 5. XP model

Keep separate ledgers:

- Learning XP: lessons, attendance, approved quizzes, tasks, and projects.
- Game XP: participation, achievements, sportsmanship, and game challenges.
- Profile XP: a presentation-layer total that combines eligible Learning XP
  and capped Game XP.

Game XP must not affect grades, badges, certificates, curriculum completion, or
assessment eligibility. Daily game XP should have a cap so repetitive play
cannot dominate the profile economy.

This separate-ledger model and the combined Profile XP presentation are
confirmed product requirements. Profile XP is motivational only. Learning XP
and Game XP remain independently queryable and auditable, and no Profile XP
total may be used to infer or alter formal academic achievement.

## 6. Leaderboards

Supported periods:

- Daily
- Weekly
- Termly
- All-time

Daily, weekly, and termly boards are visible to eligible learners and coaches.
All-time boards are limited to school and platform administrators.

Boards must specify:

- Game
- School
- Optional class
- Age band
- Period
- Ranking metric
- Minimum eligible activity

Preferred names and avatars are shown to learners. Real names and administrative
profiles are not exposed to other learners.

## 7. Multiplayer architecture

- Presence shows only eligible same-school players by default.
- Invitations are durable records with expiry and status.
- Shareable links contain an opaque, expiring invitation token and require an
  authenticated eligible account.
- Moves are submitted to the server for authorization and rule validation.
- The server determines the result and writes rewards.
- Realtime channels distribute accepted events to clients.
- Reconnect restores state from the durable match record.
- Timeouts, resignation, abandoned matches, draws, rematches, and disputes have
  explicit state transitions.

## 8. Fair play

- Rate-limit moves and invitations.
- Reject impossible or out-of-order moves.
- Record client and server timestamps.
- Detect repeated collusion, farming, and suspicious score patterns.
- Exclude unverified offline scores from competitive boards.
- Provide report, block, mute, and moderator-review flows.
- Never let the client directly write an outcome or XP award.

## 9. Offline games

Single-player Word Scramble, Guessing Game, and the falling-block puzzle may
support offline play. Chess and checkers may support local play against the
device later.

Offline sessions can contribute to personal history after synchronization but
must remain ineligible for competitive leaderboards unless the game has a
verifiable replay and server validation.

## 10. Content operations

Word and clue packs require:

- Age band
- Curriculum relationship where applicable
- Difficulty
- Locale
- Content review status
- Source and author
- Version
- Safe-language review

Content contributors need a preview and publishing workflow rather than direct
database editing.

1. Weekly Leaderboard based on XP
2. Multiplayer.
3. Start with  or 3 games
4. send invite to friends to play the games or copy code. 
5. Game functionality, visuals (not specific), 

6. There's a time limit to how long you can play games. 2hours per day. It can be increased or decreased by school admin or coach
7. Next.js and Fast API. 
8. He started working on game stuff.
9. Single player mode can work offline.