# Roles and Sponsor/Bar Foundation — Design

**Date:** 2026-05-04
**Status:** Approved (pending implementation plan)
**Sub-project:** A of A→B→C→D decomposition

## Decomposition context

The full feature request (league operator role, sponsor/bar role, captain/co-captain/scorekeeper, dual independent scoring with conflict detection, public/private tournaments, tournament sharing) is too large for one spec. It is split into:

- **A. Roles + Sponsor/Bar entity foundation** — this document.
- **B. Team model + roster management** — captain, co-captain, scorekeeper, sub assignments. Depends on A.
- **C. Tournament visibility + sharing** — public/private flag, anonymous viewing, sponsor-to-sponsor sharing, tournament officials. Depends on A.
- **D. League play with dual independent scoring** — scheduled team-vs-team matches, two-sided scoring with mismatch detection. Depends on A and B.

This document covers only A.

## Goals

1. Distinguish a "League Operator" capability (can create leagues) from a regular user.
2. Introduce a `Bar` first-class entity that can sponsor teams in one or more leagues.
3. Allow a single Bar to have a primary Sponsor login plus invitable Bar Staff sub-accounts with equivalent powers.
4. Allow a single human to wear multiple hats (e.g., be a Sponsor at one bar and a Player on a team elsewhere) without juggling logins.
5. Reserve the `PlayerProfile.user_id` column so that Project B can link players to logins without another schema migration.

## Non-goals

- Teams, captains, co-captains, scorekeepers, subs (Project B).
- Tournament public/private visibility, anonymous viewing, tournament officials, tournament sharing (Project C).
- Dual scoring, league play scheduling, conflict resolution (Project D).
- Self-signup for any role. All accounts are created by an admin, a league operator, or a primary sponsor.

## Decisions locked in during brainstorming

- **Q1 — Sponsor scoping:** Bar is a first-class entity. One Bar can sponsor in many leagues via a `LeagueSponsorship` join. (Option b.)
- **Q2 — Bar↔User cardinality:** One primary Sponsor login per Bar plus invitable Bar Staff sub-accounts; primary and staff have equal powers within the bar except primary is the only role that can invite/remove other staff. (Option c.)
- **Q3 — Multi-hat users:** Per-membership roles. No `role` enum on User. Powers come from `BarMembership`, `LeagueOwner` (existing `League.owner_id`), `ManagerShare` (existing), and (later) `PlayerProfile.user_id`. Two boolean global capabilities live on User: `is_admin`, `is_league_operator`. (Option b.)

## Architecture — Approach 1 (selected)

Membership-only authorization, fully decoupled Bar/League. Approach 2 (Bar locked to a single League) was rejected because it contradicts Q1. Approach 3 (capability table) was rejected as premature abstraction for two known global capabilities.

## Data model

### User (renamed from `Admin`)

Existing table `admin` is renamed to `user`. The `role` column is replaced by two booleans.

| column                | type         | notes                                       |
| --------------------- | ------------ | ------------------------------------------- |
| id                    | integer PK   | unchanged                                   |
| username              | varchar(80)  | unique, unchanged                           |
| password_hash         | varchar(200) | unchanged                                   |
| is_admin              | bool         | new. defaults to 0                          |
| is_league_operator    | bool         | new. defaults to 0                          |
| ~~role~~              | dropped      | backfilled into the two booleans            |

### PlayerProfile (additive)

| column   | type    | notes                                        |
| -------- | ------- | -------------------------------------------- |
| user_id  | integer | new, nullable, FK → user.id. Reserved for B. |

### Bar (new)

| column        | type         | notes                |
| ------------- | ------------ | -------------------- |
| id            | integer PK   |                      |
| name          | varchar(120) | NOT NULL             |
| address       | varchar(200) | nullable             |
| phone         | varchar(30)  | nullable             |
| created_by_id | integer      | FK → user.id         |
| created_at    | timestamp    |                      |

### BarMembership (new)

| column     | type    | notes                                    |
| ---------- | ------- | ---------------------------------------- |
| id         | integer PK |                                       |
| user_id    | integer | NOT NULL, FK → user.id                   |
| bar_id     | integer | NOT NULL, FK → bar.id                    |
| is_primary | bool    | NOT NULL, default 0                      |

Constraints:
- `UNIQUE (user_id, bar_id)` — a user has at most one membership row per bar.
- Partial unique index on `(bar_id) WHERE is_primary = 1` — exactly one primary per bar. SQLite supports partial indexes; if portability is required later, an app-level check enforces this.

### LeagueSponsorship (new)

| column        | type      | notes                       |
| ------------- | --------- | --------------------------- |
| id            | integer PK |                            |
| league_id     | integer   | NOT NULL, FK → league.id    |
| bar_id        | integer   | NOT NULL, FK → bar.id       |
| invited_by_id | integer   | FK → user.id                |
| invited_at    | timestamp |                             |

Constraint: `UNIQUE (league_id, bar_id)`.

### Existing tables (unchanged in A)

`League`, `ManagerShare`, `Tournament`, `Match`, `Participant`. Authorization for tournaments and players is unchanged in A; Project C revisits it.

## Authorization rules

A new module `auth_helpers.py` exposes named predicates. Routes use them via decorators or inline checks. Existing `League.can_manage` and `Tournament.can_manage` are preserved.

### Global capabilities

- `can_create_league(user)` → `user.is_admin or user.is_league_operator`.
- `can_create_bar(user)` → `user.is_admin or user.is_league_operator`. Operators create the Bar entity when onboarding a sponsor.
- `can_promote_user(user)` → `user.is_admin` only. Only admins can flip `is_league_operator` on another user; operators do not create operators.

### Bar-scoped

- `Bar.can_manage(user)` → admin, or any `BarMembership.user_id == user.id` for that bar. Both primary and staff have equal powers within the bar.
- `Bar.can_manage_staff(user)` → admin, or membership row where `is_primary = 1`. The only thing primary-vs-staff distinguishes.

### League-scoped (existing)

- `League.can_manage(user)` → admin, owner, or `ManagerShare` delegate. Unchanged.
- Note: `League.can_manage` does **not** depend on `is_league_operator`. Owning a league or being a `ManagerShare` delegate is sufficient to manage it. The `is_league_operator` flag gates only the *creation* of new leagues.

### Sponsorship-scoped

- `Sponsorship.can_act(user, league, bar)` → `Bar.can_manage(user)` AND a `LeagueSponsorship(league, bar)` row exists.

  This is the gate later projects will use whenever a sponsor acts inside a specific league (creating teams, designating tournament officials). Project A defines and tests it; no routes consume it yet.

## Routes and UI changes

### Admin panel — `routes/admin.py`, `templates/admin.html`

- Replace the single `role` dropdown in the "Add user" form with two checkboxes: `is_admin`, `is_league_operator`. Either, both, or neither is allowed.
- Add a "Bars" section listing every `Bar` row with its primary sponsor and league memberships. Admin-only.

### League dashboard — `routes/leagues.py`, `templates/league_dashboard.html`

- New "Sponsors" panel listing `LeagueSponsorship` rows for this league. Each row shows Bar name and primary sponsor username. Visible only to users for whom `League.can_manage` returns true.
- "Add sponsor" action with two paths:
  - **Invite existing Bar:** type-ahead search of Bars not currently sponsoring this league; on submit creates a `LeagueSponsorship`.
  - **Onboard new Bar:** form with Bar name plus primary sponsor username and password. Creates `Bar` + `User` (`is_admin=0`, `is_league_operator=0`) + `BarMembership(is_primary=1)` + `LeagueSponsorship` in one transaction.
- "Remove sponsor" action deletes the `LeagueSponsorship` row. Does not delete the Bar or its users.

### New "My Bar" page — `routes/bars.py`, `templates/bar_dashboard.html`

- Visible to users with at least one `BarMembership`.
- Shows the Bar's profile, the list of leagues the bar is sponsoring, and (primary only) a Bar Staff section to invite/remove additional users.
- Project A scope ends at the staff list. Team management lands in Project B.

### Login redirect

After Project A, post-login routing is:

- Admin or user with any league access → existing `leagues.league_list`.
- Otherwise, if the user has at least one `BarMembership` → `bars.bar_dashboard`.
- Otherwise → `tournaments.index` (the existing public landing).

### Untouched in Project A

Tournament views, player roster pages, bracket pages.

## Error handling and edge cases

- Onboarding a new Bar with a username that already exists → 400 "Username already taken." The operator picks a different username. (Inviting an existing user as bar staff arrives later when primary's invite flow lands.)
- Removing a `LeagueSponsorship` while teams exist for that bar in that league → blocked in Project D. No check needed in A because teams do not yet exist.
- Deleting a `Bar` → allowed only if zero `LeagueSponsorship` rows and zero `BarMembership` rows. Otherwise 400 "Detach all sponsorships and members first." Admin override is available.
- Demoting a user (`is_league_operator: 1 → 0`) is allowed even if they own leagues. They retain ownership and full management rights on their existing leagues (those flow from `League.owner_id`, not the global flag) but cannot create new ones.
- Two operators concurrently inviting the same Bar to the same league → the `UNIQUE (league_id, bar_id)` constraint catches the second insert; the route returns "Bar already sponsors this league."

## Testing

New test files under `tests/`, following the existing pytest setup.

- `tests/test_user_capabilities.py` — admin / league-operator / neither combinations gate `can_create_league`, `can_create_bar`, `can_promote_user`.
- `tests/test_bar_membership.py` — primary uniqueness, staff invite/remove, `Bar.can_manage`, `Bar.can_manage_staff`.
- `tests/test_league_sponsorship.py` — invite, remove, uniqueness, `Sponsorship.can_act` matrix.
- `tests/test_migration_admin_to_user.py` — fixture with old `Admin` rows (`role='admin'`, `role='manager'`); run migration; assert `is_admin` and `is_league_operator` are set correctly and `role` is dropped.
- Route tests for sponsor onboarding (happy path, duplicate username, bar already sponsoring league).

## Migration and rollout

A single migration step. SQLite is the production database; the `ALTER TABLE` style currently used in `app.py` is preserved or moved to Alembic at the implementer's discretion.

1. Rename `admin` → `user` (SQLite requires table rebuild).
2. Add `user.is_admin` and `user.is_league_operator` columns, default 0.
3. Backfill: `role='admin'` → `is_admin=1`; `role='manager'` → `is_league_operator=1`.
4. Drop `user.role`.
5. Add `player_profile.user_id` (nullable, FK → user.id).
6. Create `bar`, `bar_membership`, `league_sponsorship` tables and indexes.
7. No data backfill for new tables.

Existing functionality (leagues, tournaments, manager shares, players) continues to work. The only visible behavior change pre-Project-B is the admin panel showing a Bars section and the league dashboard showing a Sponsors panel.

## Open questions deferred to later projects

- How a Player gets a login and links to their `PlayerProfile.user_id` — Project B.
- How a Sponsor designates a tournament official from their player roster — Project C.
- How dual scoring is collected and reconciled — Project D.
