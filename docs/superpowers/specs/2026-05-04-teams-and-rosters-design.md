# Teams and Rosters — Design

**Date:** 2026-05-04
**Status:** Approved (pending implementation plan)
**Sub-project:** B of A→B→C→D decomposition

## Decomposition context

Sub-project B of the larger feature. Project A (roles + sponsor/bar foundation) is implemented and merged. This document covers only B.

- A. Roles + Sponsor/Bar foundation — implemented.
- B. Team model + roster management — this document.
- C. Tournament visibility, sharing, tournament officials — pending.
- D. League play with dual independent scoring — pending. Depends on B.

## Goals

1. Add a `Team` entity sponsored by a Bar and competing in a single League.
2. Track roster membership with role flags (Captain, Co-Captain, Scorekeeper, Sub) on `TeamMembership` rows.
3. Distinguish roster subs (pre-designated backup players on the team) from starters via `is_sub`. Per-game emergency call-up (option (c) of the brainstorm) is part of D.
4. When a player is given a role that requires a login (Captain/Co-Captain/Scorekeeper) but lacks a `user_id`, create the user account inline with credentials supplied by the assigner.
5. Surface Teams on the Bar dashboard and a "My Teams" page for any user linked to a `PlayerProfile` on a team.

## Non-goals

- Per-match substitution (calling up a roster sub or a non-roster player for one match) — Project D.
- League play scheduling, match scoring, dual-scoring conflict resolution — Project D.
- Tournament-related concerns (visibility, sharing, tournament officials) — Project C.
- Email-based invite flow for new player accounts. Account creation in B is "show credentials once to the assigner to deliver out-of-band."

## Decisions locked in during brainstorming

- **Sub mechanic:** option (c) — pre-designated subs live on the roster (`TeamMembership.is_sub = 1`); per-match call-up of non-roster players is deferred to Project D.
- **Team scoping:** every `Team` has both a `bar_id` and a `league_id` (both required). Same Bar can have multiple teams in the same league. Same Bar can have separate teams across multiple leagues. Team creation is gated on `LeagueSponsorship(bar_id, league_id)` existing.
- **Role flags:** Captain/Co-Captain/Scorekeeper/Sub are columns on `TeamMembership`, not separate tables. At most one Captain per team, at most one Co-Captain per team, scorekeeper unbounded, sub unbounded.
- **Captain & Co-Captain are designated by Bar Staff.** Captain (with Co-Captain as backup) designates Scorekeepers.
- **Player↔User linking:** assigning Captain/Co-Captain/Scorekeeper to a `PlayerProfile` without a `user_id` triggers an inline form that creates a User, sets `PlayerProfile.user_id`, and shows credentials once. Regular roster members never need a login.

## Data model

### Team (new)

| column        | type         | notes                                |
| ------------- | ------------ | ------------------------------------ |
| id            | integer PK   |                                      |
| name          | varchar(120) | NOT NULL                             |
| bar_id        | integer      | NOT NULL, FK → bar.id                |
| league_id     | integer      | NOT NULL, FK → league.id             |
| created_by_id | integer      | FK → user.id                         |
| created_at    | timestamp    |                                      |

Cascade behavior: deleting a `Bar` is already blocked while sponsorships or memberships exist (Project A). Project B adds an additional implicit guard — a Bar cannot be detached from a League while a Team for that pairing still exists. Enforced by application-level check in the `LeagueSponsorship` removal route, not at DB level.

### TeamMembership (new)

| column          | type    | notes                                              |
| --------------- | ------- | -------------------------------------------------- |
| id              | integer PK |                                                |
| team_id         | integer | NOT NULL, FK → team.id                             |
| profile_id      | integer | NOT NULL, FK → player_profile.id                   |
| is_captain      | bool    | NOT NULL DEFAULT 0                                 |
| is_co_captain   | bool    | NOT NULL DEFAULT 0                                 |
| is_scorekeeper  | bool    | NOT NULL DEFAULT 0                                 |
| is_sub          | bool    | NOT NULL DEFAULT 0                                 |

Constraints:

- `UNIQUE (team_id, profile_id)` — a player belongs to a team at most once.
- partial `UNIQUE (team_id) WHERE is_captain = 1`
- partial `UNIQUE (team_id) WHERE is_co_captain = 1`
- application-level: a row cannot have BOTH `is_captain = 1` AND `is_co_captain = 1` (the same person cannot be both — by design).

### Existing tables (unchanged)

`User`, `League`, `Bar`, `BarMembership`, `LeagueSponsorship`, `Tournament`, `Match`, `Participant`, `PlayerProfile`. The `PlayerProfile.user_id` column reserved in Project A is now consumed by the Player↔User linking flow.

## Authorization

New helpers in `auth_helpers.py` plus model-attached predicates on `Team`:

- `Team.can_manage_roster(user)` → admin, or `Bar.can_manage(user)` for `team.bar`. Manages name, league assignment, full roster including Captain/Co-Captain/Sub flags.
- `Team.can_assign_scorekeeper(user)` → admin, Bar Staff (`Team.can_manage_roster` returns True), or any `TeamMembership` row for this team where `is_captain = 1` OR `is_co_captain = 1` and `profile.user_id == user.id`.
- `Team.is_member(user)` → True if any `TeamMembership` row in this team links to a `PlayerProfile` whose `user_id == user.id`. Used to scope the "My Teams" page.
- `can_create_team(user, bar, league)` → `auth_helpers.can_act_as_sponsor(user, league, bar)`.

Existing predicates (`Bar.can_manage`, `League.can_manage`, `Tournament.can_manage`, etc.) are unchanged.

## Routes and UI

### New blueprint `routes/teams.py`

| route                                         | method | gate                                | purpose                                                              |
| --------------------------------------------- | ------ | ----------------------------------- | -------------------------------------------------------------------- |
| `/bar/<bid>/team/new`                         | POST   | `can_act_as_sponsor`                 | create a new Team for the bar in a sponsored league                   |
| `/team/<tid>`                                 | GET    | login + (Bar Staff or member or admin) | team dashboard: roster, role badges, links to bar/league               |
| `/team/<tid>/edit`                            | POST   | `Team.can_manage_roster`             | rename team or move between sponsored leagues                         |
| `/team/<tid>/delete`                          | POST   | `Team.can_manage_roster`             | delete team (blocked in D when match history exists; in B always allowed) |
| `/team/<tid>/roster/add`                      | POST   | `Team.can_manage_roster`             | add a PlayerProfile to the roster                                     |
| `/team/<tid>/roster/<mid>/remove`             | POST   | `Team.can_manage_roster`             | remove a TeamMembership                                               |
| `/team/<tid>/roster/<mid>/role`               | POST   | `Team.can_manage_roster`             | toggle `is_captain`/`is_co_captain`/`is_sub` (may create a User)      |
| `/team/<tid>/roster/<mid>/scorekeeper`        | POST   | `Team.can_assign_scorekeeper`        | toggle `is_scorekeeper` (may create a User)                            |
| `/my-teams`                                   | GET    | login                                | lists teams the user plays on, with role badges                       |

Anonymous viewing of team pages is deferred to Project C (where tournament public/private and sharing land — team visibility is part of the same axis).

### Templates

- `templates/team_dashboard.html` — team page with roster table (name, role badges, sub flag), management buttons gated to Bar Staff / Captain.
- `templates/team_form.html` — create / edit team (name, league select).
- `templates/my_teams.html` — list of teams the current user plays on.
- `templates/bar_dashboard.html` — add a "Teams" section listing the bar's teams (per league) with quick links.
- `templates/base.html` — add a "My Teams" nav entry visible whenever `current_user.team_memberships` (added via PlayerProfile→User backref) is non-empty.

### Inline account-creation flow

When Bar Staff toggles `is_captain` / `is_co_captain` on a profile without `user_id`, OR Captain toggles `is_scorekeeper` on such a profile, the route renders an interstitial page:

- Form fields: `username` (defaulted to a slugified `first_name.last_name`), `password` (6+ chars).
- On submit: create User with `is_admin=0, is_league_operator=0`; set `PlayerProfile.user_id`; flip the role flag in one transaction.
- Success page shows credentials once with a "Copy" button and an admonition to share with the player out-of-band.
- If the assigner cancels the interstitial, no role is assigned and no User is created.

A profile that already has `user_id` skips the interstitial entirely — the role toggles immediately.

## Error handling and edge cases

- Creating a Team for a league the bar doesn't sponsor → 403 with flash "Your bar isn't a sponsor of that league."
- Toggling `is_captain` on a second player when one is already captain → blocks with "There's already a captain. Demote them first."
- Same constraint for `is_co_captain`.
- Same player set as both Captain and Co-Captain via concurrent toggles → application check returns 400.
- Username collision during inline account creation → form re-rendered with the validation error; no team-state changes.
- Removing a team member who is the current Captain → unsets `is_captain` first as part of the same transaction (the row is deleted, so the partial unique index would fire otherwise).
- Removing a team member whose `PlayerProfile.user_id` is set → does NOT delete the User. The User stays around (they may be on other teams).
- Deleting a `Team` with members → cascade-deletes `TeamMembership` rows. Does not touch PlayerProfiles or Users.

## Testing

- `tests/test_team_model.py` — `Team` creation requires `LeagueSponsorship`; captain/co-captain partial-unique constraints; `is_sub` independence; `Team.can_manage_roster`/`Team.can_assign_scorekeeper`/`Team.is_member` matrix.
- `tests/test_team_account_creation.py` — assigning Captain to a profile without `user_id` creates a User and links the profile; existing `user_id` short-circuits.
- `tests/test_team_routes.py` — full route coverage including the inline-account-creation interstitial happy path and cancellation.
- `tests/test_my_teams.py` — `/my-teams` only lists teams the current user plays on.

## Migration

Additive only:

1. `CREATE TABLE team`
2. `CREATE TABLE team_membership` + the two partial unique indexes (`uq_team_captain`, `uq_team_co_captain`).
3. No data backfill — existing PlayerProfiles aren't on teams.

## Open questions deferred to later projects

- Per-match substitution UI (calling up a roster sub or a non-roster player for one match) — Project D.
- Public/anonymous viewing of team pages — Project C.
- Match-day scoring by Scorekeepers, Captain confirmation, dual scoring — Project D.
