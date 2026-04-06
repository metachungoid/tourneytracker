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

### Admin
- **Login-protected admin panel** -- only admins can create tournaments and manage results
- **Multiple admin accounts** with password management
- **Default admin** created on first run (username: `admin`, password: `admin123` -- change this immediately)

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
4. Add your player roster under Players
5. Create your first tournament
