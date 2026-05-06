# TourneyTracker

A web-based tournament management app built for pool halls and billiards leagues. Run brackets, track players, manage payouts, and keep rankings -- all from a browser.

## Features

### Tournament Management
- **Create tournaments** with custom buy-in amounts, dates, and formats
- **Tournament formats:** Single elimination, double elimination, and race-to (best of) formats
- **Bracket generation** with random or rankings-based seeding
- **Live bracket view** -- update match results in real time as games are played
- **Printable brackets** for posting at the venue
- **Prize pool calculation** -- automatically calculates payouts with customizable split percentages (e.g. 70/30, 60/30/10)
- **$1/game deduction** -- optionally deducts table fees from the prize pool once the bracket locks

### Player Management
- **Player profiles** with name, phone, email, and Fargo rating
- **Quick-add players** to tournaments directly from the registration screen
- **Player rankings** based on tournament wins and match wins

### Leagues & Bars
- **Leagues** are owned by a User and host league-wide tournaments and player profiles
- **Bars** are venues with their own dashboard and can host their own one-off recreational tournaments
- **Bar staff** -- a Bar has one *primary* member (the owner) and any number of additional staff, all able to manage the bar's tournaments

### Sponsorships
- A Bar **sponsors a League** to grant its staff the ability to act inside that league (e.g. create teams)
- League dashboards expose **invite existing bar**, **onboard a new bar**, and **remove sponsor** flows
- Sponsorship is what gates the per-league capabilities the bar's staff get -- without it, they only see their own bar

### Teams & Rosters
- **Teams** are sponsored by a Bar and compete in exactly one League (only allowed when that bar sponsors the league)
- **Rosters** are managed by Bar Staff: add or remove players from the league's player pool
- **Per-membership role flags:** Captain, Co-Captain, Scorekeeper, Sub. Each team has at most one Captain and one Co-Captain (enforced by partial unique indexes); any number of Scorekeepers and Subs
- **Captains and Co-Captains can assign Scorekeepers** on their own team
- **Inline account creation** -- promoting a player to a role that needs to log in (Captain, Co-Captain, Scorekeeper) prompts you to create a username/password for them on the spot if their `PlayerProfile` has no linked `User`
- **`/my-teams`** lists every team the logged-in user plays on, with role badges

### Roles & Access
Two role flags live on the `User` row, set independently:

| Flag | Capability |
|------|------------|
| `is_admin` | Bypasses all permission checks; can create leagues and bars; can promote other users to League Operator from the Admin panel |
| `is_league_operator` | Can create new leagues and bars; manages anything they own |

Beyond those flags, finer-grained access is **earned by relationship**:
- **League ownership** -> manage the league
- **Bar membership** -> manage the bar (and any tournaments it hosts)
- **Bar membership + LeagueSponsorship** -> act as a sponsor inside that league (e.g. create teams)
- **TeamMembership.is_captain / is_co_captain** -> assign scorekeepers on that team

The default admin (`admin` / `admin123`) is created on first run -- **change the password immediately**.

After login, users land on the most relevant page they have access to: **a league they own** > **a bar they belong to** > the public home.

## Data Model

```
User ──owns──> League ─────────hosts────> Tournament ──> Match
 │              ▲                            ▲
 │              │ sponsored_by               │ optionally hosted_by
 │              │                            │
 │              └── LeagueSponsorship ──> Bar ──hosts──> Tournament (recreational)
 │                                        │
 │                                        └── BarMembership <── User (staff; one is_primary)
 │
 │  PlayerProfile ──(optional user_id)──> User (login)
 │       │
 │       └── TeamMembership ──> Team ──sponsored_by──> Bar
 │              (role flags)         └──competes_in──> League
 │
 └─ Team.creator
```

| Entity | Purpose | Key fields |
|--------|---------|-----------|
| `User` | Login account | `username`, `password_hash`, `is_admin`, `is_league_operator` |
| `League` | A competitive container with rankings and tournaments | `name`, `owner_id` |
| `Bar` | A venue with staff, sponsorships, and recreational tournaments | `name`, `created_by_id` |
| `BarMembership` | Joins User <-> Bar | `user_id`, `bar_id`, `is_primary` (partial-unique per bar) |
| `LeagueSponsorship` | Joins League <-> Bar | `league_id`, `bar_id`, `invited_by_id`, `invited_at` |
| `PlayerProfile` | A player record (with rating, stats); optionally linked to a `User` for login | `first_name`, `last_name`, `league_id`, `user_id` (nullable) |
| `Tournament` | A bracket; belongs to *either* a league or a bar (mutually exclusive) | `name`, `format`, `league_id` xor `bar_id` |
| `Team` | A roster sponsored by a bar competing in a league | `name`, `bar_id`, `league_id` |
| `TeamMembership` | Joins Team <-> PlayerProfile with role flags | `team_id`, `profile_id`, `is_captain`, `is_co_captain`, `is_scorekeeper`, `is_sub` |
| `Participant` / `Match` | Bracket entries and the matches between them | -- |

Authorization predicates live next to the data they protect: `League.can_manage`, `Bar.can_manage`, `Bar.can_manage_staff`, `Tournament.can_manage`, `Team.can_manage_roster`, `Team.can_assign_scorekeeper`, `Team.is_member`. Cross-cutting checks (`can_create_league`, `can_create_bar`, `can_promote_user`, `can_act_as_sponsor`, `can_create_team`) live in `auth_helpers.py`.

## Running Locally

### Prerequisites
- Python 3.10+

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app will be available at **http://localhost:5050**.

## Running with Docker

```bash
docker compose up --build
```

This starts the app at **http://localhost:5050** with the SQLite database persisted in the `instance/` directory.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `tourney-super-secret-2025` | Flask session secret -- set to a random string in production |
| `DATABASE_URI` | `sqlite:///tourneytracker.db` | Database connection string |
| `FLASK_DEBUG` | `0` | Set to `1` to enable debug mode |

## Deploying to Unraid

### 1. Set up automatic Docker builds

This repo includes a GitHub Actions workflow that automatically builds a Docker image and pushes it to GitHub Container Registry whenever you push to `main`. No extra setup is needed -- GitHub Actions uses the built-in `GITHUB_TOKEN`.

If your repo is **private**, go to your package settings on GitHub and ensure your Unraid server has read access, or create a Personal Access Token (PAT) with `read:packages` scope.

### 2. Add the container in Unraid

Go to the **Docker** tab in Unraid and click **Add Container**:

| Field | Value |
|-------|-------|
| **Repository** | `ghcr.io/<your-github-username>/tourneytracker:latest` |
| **Port mapping** | Host `5050` -> Container `5050` |
| **Volume mapping** | Host `/mnt/user/appdata/tourneytracker/instance` -> Container `/app/instance` |
| **Variable: SECRET_KEY** | A strong random string |

The volume mapping is important -- it stores your SQLite database outside the container so your data survives updates.

### 3. Set up automatic updates with Watchtower

Install **Watchtower** from Unraid Community Applications to automatically pull new images when you push code:

| Field | Value |
|-------|-------|
| **Repository** | `containrrr/watchtower` |
| **Volume** | `/var/run/docker.sock:/var/run/docker.sock` |
| **Variable: WATCHTOWER_POLL_INTERVAL** | `300` (checks every 5 minutes) |
| **Variable: WATCHTOWER_CLEANUP** | `true` |

If your GitHub repo is private, Watchtower needs registry credentials. Create the file `/mnt/user/appdata/watchtower/config.json`:

```json
{
  "auths": {
    "ghcr.io": {
      "auth": "<base64-encoded username:PAT>"
    }
  }
}
```

Then add a volume mapping to Watchtower: `/mnt/user/appdata/watchtower/config.json:/config.json` and set the environment variable `DOCKER_CONFIG=/`.

### How updates work

```
Push code to main
  -> GitHub Actions builds a new Docker image
    -> Pushes to ghcr.io
      -> Watchtower detects the new image (within 5 minutes)
        -> Pulls the new image and recreates the container
          -> Your database is preserved via the volume mount
```

You just push code and your Unraid server updates itself.

## First-time setup after deploy

1. Open the app at `http://<your-unraid-ip>:5050`
2. Log in with the default credentials: **admin** / **admin123**
3. **Change the admin password immediately** from the Admin panel
4. (Optional) From the Admin panel, promote one or more users to **League Operator** so they can run their own leagues and bars
5. Create a **League** (or have a League Operator do it)
6. Create a **Bar** and have its primary member invite any additional staff
7. From the league dashboard, **invite the bar to sponsor the league**
8. Add your player roster under Players (or per-league via the league dashboard)
9. From the bar dashboard, create a **Team** in the sponsored league and add players to its roster; promote a Captain to unlock the inline-account-creation flow
10. Create your first tournament
