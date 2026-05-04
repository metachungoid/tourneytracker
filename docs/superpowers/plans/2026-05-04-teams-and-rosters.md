# Teams and Rosters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Team` entity sponsored by a Bar and competing in a single League, with a `TeamMembership` model for roster + role flags (Captain, Co-Captain, Scorekeeper, Sub) and an inline flow that creates a User account when a role requiring login is assigned to a `PlayerProfile` without `user_id`.

**Architecture:** Two new tables (`team`, `team_membership`) with partial unique indexes on captain/co-captain. New blueprint `routes/teams.py`. New `Team` model methods for authorization (`can_manage_roster`, `can_assign_scorekeeper`, `is_member`). Inline interstitial form for account creation when needed; otherwise role toggles are immediate.

**Tech Stack:** Flask, SQLAlchemy, Flask-Login, SQLite, pytest.

**Branch:** Branch from `feature/roles-and-sponsor-foundation` (Project A) since this builds on those tables. Once A is merged to main, rebase.

---

## File Structure

**New files:**
- `routes/teams.py` — blueprint for team management.
- `templates/team_dashboard.html` — team page with roster.
- `templates/team_form.html` — create/edit team form.
- `templates/my_teams.html` — list of teams the current user plays on.
- `templates/inline_account_create.html` — interstitial for User-creation when assigning a role requiring login.
- `tests/test_team_model.py`
- `tests/test_team_account_creation.py`
- `tests/test_team_routes.py`
- `tests/test_my_teams.py`

**Modified files:**
- `models.py` — add `Team`, `TeamMembership` models; `PlayerProfile.user` and reverse `User.player_profile` relationships.
- `app.py` — add `CREATE TABLE` migrations for `team`, `team_membership`, plus the partial unique indexes.
- `routes/__init__.py` — register `teams` blueprint.
- `templates/bar_dashboard.html` — add "Teams" section listing the bar's teams.
- `templates/base.html` — add "My Teams" nav link.
- `auth_helpers.py` — add `can_create_team`.

---

## Task 1: Team model and table

**Files:**
- Modify: `models.py`
- Modify: `app.py`
- Test: `tests/test_team_model.py`

- [ ] **Step 1: Failing test**

Create `tests/test_team_model.py`:

```python
from datetime import datetime
from app import db
from models import User, Bar, League, LeagueSponsorship, Team


def _user(username='tu_admin', **flags):
    u = User(username=username, is_admin=flags.get('is_admin', False),
             is_league_operator=flags.get('is_league_operator', False))
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def _bar_and_league(creator):
    bar = Bar(name='Cactus', created_by_id=creator.id, created_at=datetime.utcnow())
    league = League(name='WSPA', owner_id=creator.id)
    db.session.add_all([bar, league])
    db.session.flush()
    db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                     invited_by_id=creator.id,
                                     invited_at=datetime.utcnow()))
    db.session.commit()
    return bar, league


def test_team_creation_persists(app):
    with app.app_context():
        u = _user('tu1', is_admin=True)
        bar, league = _bar_and_league(u)
        t = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                 created_by_id=u.id, created_at=datetime.utcnow())
        db.session.add(t)
        db.session.commit()
        fetched = Team.query.first()
        assert fetched.name == 'Cactus A'
        assert fetched.bar_id == bar.id
        assert fetched.league_id == league.id


def test_team_requires_name(app):
    with app.app_context():
        from sqlalchemy.exc import IntegrityError
        u = _user('tu2', is_admin=True)
        bar, league = _bar_and_league(u)
        t = Team(name=None, bar_id=bar.id, league_id=league.id)
        db.session.add(t)
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()
```

- [ ] **Step 2: Run and confirm failure**

Run: `/home/flip/tourneytracker/.venv/bin/python -m pytest tests/test_team_model.py -v`
Expected: `ImportError: cannot import name 'Team'`.

- [ ] **Step 3: Add the Team model**

In `models.py`, append (after `LeagueSponsorship`):

```python
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    bar_id = db.Column(db.Integer, db.ForeignKey('bar.id'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)

    bar = db.relationship('Bar', foreign_keys=[bar_id], backref='teams')
    league = db.relationship('League', foreign_keys=[league_id], backref='teams')
    creator = db.relationship('User', foreign_keys=[created_by_id])
    memberships = db.relationship(
        'TeamMembership', backref='team', lazy=True, cascade='all, delete-orphan'
    )
```

- [ ] **Step 4: Add the migration**

Append to the `col_sql` list in `app.py`:

```python
"""CREATE TABLE IF NOT EXISTS team (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(120) NOT NULL,
    bar_id INTEGER NOT NULL REFERENCES bar(id),
    league_id INTEGER NOT NULL REFERENCES league(id),
    created_by_id INTEGER REFERENCES user(id),
    created_at TIMESTAMP
)""",
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_team_model.py -v`
Expected: 2 PASS.

Run full suite: `pytest -q`
Expected: all green (243 + 2 = 245 passing).

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_team_model.py
git -c commit.gpgsign=false commit -m "models: add Team entity"
```

---

## Task 2: TeamMembership model with role flags

**Files:**
- Modify: `models.py`
- Modify: `app.py`
- Test: `tests/test_team_model.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_team_model.py`:

```python
from sqlalchemy.exc import IntegrityError
from models import PlayerProfile, TeamMembership


def _team_with_player(app, profile_kwargs=None):
    u = _user('tu_helper', is_admin=True)
    bar, league = _bar_and_league(u)
    team = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                created_by_id=u.id, created_at=datetime.utcnow())
    db.session.add(team)
    db.session.flush()
    profile = PlayerProfile(first_name='John', last_name='Doe',
                            league_id=league.id, **(profile_kwargs or {}))
    db.session.add(profile)
    db.session.commit()
    return u, bar, league, team, profile


def test_team_membership_persists(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        m = TeamMembership(team_id=team.id, profile_id=profile.id,
                           is_captain=True)
        db.session.add(m)
        db.session.commit()
        fetched = TeamMembership.query.first()
        assert fetched.is_captain is True
        assert fetched.is_co_captain is False
        assert fetched.is_scorekeeper is False
        assert fetched.is_sub is False


def test_team_member_unique(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_captain_per_team(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        db.session.add(p2)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=p2.id, is_captain=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_co_captain_per_team(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        db.session.add(p2)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id, is_co_captain=True))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=p2.id, is_co_captain=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_many_scorekeepers_allowed(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        p3 = PlayerProfile(first_name='Joe', last_name='Schmoe', league_id=league.id)
        db.session.add_all([p2, p3])
        db.session.flush()
        for p in (profile, p2, p3):
            db.session.add(TeamMembership(team_id=team.id, profile_id=p.id, is_scorekeeper=True))
        db.session.commit()
        assert TeamMembership.query.filter_by(team_id=team.id, is_scorekeeper=True).count() == 3
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_team_model.py -v`
Expected: 5 new failures with `ImportError: cannot import name 'TeamMembership'`.

- [ ] **Step 3: Add the TeamMembership model**

Append to `models.py` (after `Team`):

```python
class TeamMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    profile_id = db.Column(db.Integer, db.ForeignKey('player_profile.id'), nullable=False)
    is_captain = db.Column(db.Boolean, nullable=False, default=False)
    is_co_captain = db.Column(db.Boolean, nullable=False, default=False)
    is_scorekeeper = db.Column(db.Boolean, nullable=False, default=False)
    is_sub = db.Column(db.Boolean, nullable=False, default=False)

    profile = db.relationship('PlayerProfile', foreign_keys=[profile_id],
                              backref=db.backref('team_memberships', cascade='all'))

    __table_args__ = (
        db.UniqueConstraint('team_id', 'profile_id', name='uq_team_membership_team_profile'),
        db.Index('uq_team_captain', 'team_id',
                 unique=True, sqlite_where=db.text('is_captain = 1')),
        db.Index('uq_team_co_captain', 'team_id',
                 unique=True, sqlite_where=db.text('is_co_captain = 1')),
    )
```

- [ ] **Step 4: Add the migration**

Append to `app.py` `col_sql`:

```python
"""CREATE TABLE IF NOT EXISTS team_membership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES team(id),
    profile_id INTEGER NOT NULL REFERENCES player_profile(id),
    is_captain BOOLEAN NOT NULL DEFAULT 0,
    is_co_captain BOOLEAN NOT NULL DEFAULT 0,
    is_scorekeeper BOOLEAN NOT NULL DEFAULT 0,
    is_sub BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE (team_id, profile_id)
)""",
"CREATE UNIQUE INDEX IF NOT EXISTS uq_team_captain ON team_membership (team_id) WHERE is_captain = 1",
"CREATE UNIQUE INDEX IF NOT EXISTS uq_team_co_captain ON team_membership (team_id) WHERE is_co_captain = 1",
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_team_model.py -v`
Expected: 7 PASS (2 from Task 1 + 5 here).

Full suite: 250 passing.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_team_model.py
git -c commit.gpgsign=false commit -m "models: add TeamMembership with role flags"
```

---

## Task 3: Team authorization predicates

**Files:**
- Modify: `models.py`
- Modify: `auth_helpers.py`
- Test: `tests/test_team_model.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_team_model.py`:

```python
from auth_helpers import can_create_team


def test_can_create_team_requires_sponsorship(app):
    with app.app_context():
        admin = _user('cct_admin', is_admin=True)
        bar = Bar(name='B', created_by_id=admin.id, created_at=datetime.utcnow())
        league = League(name='L', owner_id=admin.id)
        db.session.add_all([bar, league])
        db.session.commit()
        # No LeagueSponsorship row → cannot create even as admin? Yes, because creation
        # is gated on sponsorship existing for non-admins. Admins always pass.
        assert can_create_team(admin, bar, league) is True

        sponsor = _user('cct_sponsor')
        from models import BarMembership
        db.session.add(BarMembership(user_id=sponsor.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # Bar member but no sponsorship → False.
        assert can_create_team(sponsor, bar, league) is False

        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        assert can_create_team(sponsor, bar, league) is True


def test_team_can_manage_roster(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        admin = u  # already admin
        assert team.can_manage_roster(admin) is True

        outsider = _user('tcr_outsider')
        assert team.can_manage_roster(outsider) is False

        from models import BarMembership
        staff = _user('tcr_staff')
        db.session.add(BarMembership(user_id=staff.id, bar_id=bar.id, is_primary=False))
        db.session.commit()
        assert team.can_manage_roster(staff) is True


def test_team_can_assign_scorekeeper(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        admin = u
        assert team.can_assign_scorekeeper(admin) is True

        # Captain assigned via team membership; profile.user_id linked.
        captain_user = _user('cap')
        profile.user_id = captain_user.id
        m = TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True)
        db.session.add(m)
        db.session.commit()
        assert team.can_assign_scorekeeper(captain_user) is True

        outsider = _user('cap_outsider')
        assert team.can_assign_scorekeeper(outsider) is False


def test_team_is_member(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        member_user = _user('member')
        profile.user_id = member_user.id
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        db.session.commit()
        assert team.is_member(member_user) is True

        non_member = _user('non_member')
        assert team.is_member(non_member) is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_team_model.py -v`
Expected: 4 new failures (`ImportError: can_create_team` etc.).

- [ ] **Step 3: Add `can_create_team` to `auth_helpers.py`**

Append to `auth_helpers.py`:

```python
def can_create_team(user, bar, league):
    """A team can be created when its bar sponsors its league.

    Admins always pass; otherwise both bar membership AND a
    LeagueSponsorship row are required (delegates to can_act_as_sponsor).
    """
    return can_act_as_sponsor(user, league, bar)
```

- [ ] **Step 4: Add `Team.can_manage_roster`, `Team.can_assign_scorekeeper`, `Team.is_member` to `models.py`**

Inside the `Team` class, add:

```python
    def can_manage_roster(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        return self.bar.can_manage(user)

    def can_assign_scorekeeper(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        if self.can_manage_roster(user):
            return True
        # captain or co-captain on this team
        return TeamMembership.query.filter(
            TeamMembership.team_id == self.id,
            db.or_(TeamMembership.is_captain == True,    # noqa: E712
                   TeamMembership.is_co_captain == True),  # noqa: E712
            TeamMembership.profile.has(user_id=user.id),
        ).first() is not None

    def is_member(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return TeamMembership.query.filter(
            TeamMembership.team_id == self.id,
            TeamMembership.profile.has(user_id=user.id),
        ).first() is not None
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_team_model.py -v`
Expected: 11 PASS (7 prior + 4 new).

Full suite green.

- [ ] **Step 6: Commit**

```bash
git add models.py auth_helpers.py tests/test_team_model.py
git -c commit.gpgsign=false commit -m "auth: add can_create_team and Team.can_manage_roster/can_assign_scorekeeper/is_member"
```

---

## Task 4: Team creation route + form on bar dashboard

**Files:**
- Create: `routes/teams.py`
- Modify: `routes/__init__.py`
- Modify: `templates/bar_dashboard.html`
- Test: `tests/test_team_routes.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_team_routes.py`:

```python
from datetime import datetime
from app import db
from models import User, Bar, BarMembership, League, LeagueSponsorship, Team


def _create_user(username, password='secret123', **flags):
    u = User(username=username,
             is_admin=flags.get('is_admin', False),
             is_league_operator=flags.get('is_league_operator', False))
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password='secret123'):
    return client.post('/login', data={'username': username, 'password': password})


def _seed_bar_and_league(app, sponsored=True):
    creator = _create_user('tr_creator', is_admin=True)
    sponsor = _create_user('tr_sponsor')
    bar = Bar(name='Cactus', created_by_id=creator.id, created_at=datetime.utcnow())
    league = League(name='WSPA', owner_id=creator.id)
    db.session.add_all([bar, league])
    db.session.flush()
    db.session.add(BarMembership(user_id=sponsor.id, bar_id=bar.id, is_primary=True))
    if sponsored:
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=creator.id,
                                         invited_at=datetime.utcnow()))
    db.session.commit()
    return creator, sponsor, bar, league


def test_sponsor_creates_team(app):
    with app.app_context():
        _, sponsor, bar, league = _seed_bar_and_league(app)
        bid, lid = bar.id, league.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/bar/{bid}/team/new', data={
        'name': 'Cactus A', 'league_id': str(lid),
    })
    assert resp.status_code == 302
    with app.app_context():
        t = Team.query.filter_by(name='Cactus A').first()
        assert t is not None
        assert t.bar_id == bid
        assert t.league_id == lid


def test_create_team_blocked_without_sponsorship(app):
    with app.app_context():
        _, sponsor, bar, league = _seed_bar_and_league(app, sponsored=False)
        bid, lid = bar.id, league.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/bar/{bid}/team/new', data={
        'name': 'Cactus A', 'league_id': str(lid),
    })
    assert resp.status_code == 403


def test_create_team_outsider_denied(app):
    with app.app_context():
        _, _, bar, league = _seed_bar_and_league(app)
        outsider = _create_user('tr_out')
        bid, lid = bar.id, league.id
    client = app.test_client()
    _login(client, 'tr_out')
    resp = client.post(f'/bar/{bid}/team/new', data={
        'name': 'Cactus A', 'league_id': str(lid),
    })
    assert resp.status_code == 403
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_team_routes.py -v`
Expected: 404s — blueprint not registered.

- [ ] **Step 3: Create `routes/teams.py`**

```python
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import Bar, League, LeagueSponsorship, Team
from auth_helpers import can_create_team

bp = Blueprint('teams', __name__)


@bp.route('/bar/<int:bid>/team/new', methods=['POST'])
@login_required
def new_team(bid):
    bar = Bar.query.get_or_404(bid)
    league_id = request.form.get('league_id', type=int)
    if not league_id:
        flash('Pick a league.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    league = League.query.get_or_404(league_id)
    if not can_create_team(current_user, bar, league):
        abort(403)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Team name required.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    t = Team(name=name, bar_id=bid, league_id=league_id,
             created_by_id=current_user.id, created_at=datetime.utcnow())
    db.session.add(t)
    db.session.commit()
    return redirect(url_for('teams.team_dashboard', tid=t.id))


@bp.route('/team/<int:tid>')
@login_required
def team_dashboard(tid):
    team = Team.query.get_or_404(tid)
    if not (team.can_manage_roster(current_user) or team.is_member(current_user)):
        abort(403)
    return render_template('team_dashboard.html', team=team)
```

- [ ] **Step 4: Register the blueprint**

In `routes/__init__.py`, add `from routes.teams import bp as teams_bp` and `app.register_blueprint(teams_bp)`.

- [ ] **Step 5: Create `templates/team_dashboard.html`** (minimal — Task 6 expands it)

```html
{% extends 'base.html' %}
{% block title %}{{ team.name }} — TourneyTracker{% endblock %}
{% block content %}
<header class="page-hero">
  <h1 class="page-hero__title">{{ team.name }}</h1>
  <p class="page-hero__sub">{{ team.bar.name }} · {{ team.league.name }}</p>
</header>
<p class="muted">Roster management lands in the next task.</p>
{% endblock %}
```

- [ ] **Step 6: Add the team-create form to `templates/bar_dashboard.html`**

In the bar dashboard, add a "Teams" section near the recreational tournaments section:

```html
<section class="admin-block">
  <div class="section-head">
    <h2 class="section-head__title">Teams</h2>
  </div>
  {% set bar_teams = bar.teams %}
  {% if bar_teams %}
    <ul class="sponsors-list">
      {% for t in bar_teams %}
        <li><a href="{{ url_for('teams.team_dashboard', tid=t.id) }}">{{ t.name }}</a> <span class="muted">· {{ t.league.name }}</span></li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">No teams yet.</p>
  {% endif %}
  <form method="post" action="{{ url_for('teams.new_team', bid=bar.id) }}" class="form-stack form-stack--inline">
    <input type="text" name="name" class="form-control" placeholder="Team name" required>
    <select name="league_id" class="form-control" required>
      <option value="">Pick a league…</option>
      {% for ls in sponsorships %}
        <option value="{{ ls.league_id }}">{{ ls.league.name }}</option>
      {% endfor %}
    </select>
    <button class="btn btn-primary">Create team</button>
  </form>
</section>
```

`sponsorships` is already passed to the bar dashboard template from Project A.

- [ ] **Step 7: Run and confirm pass**

Run: `pytest tests/test_team_routes.py -v`
Expected: 3 PASS.

Full suite: 254 passing (250 + 3 + 1 from Task 3? recount). Run `pytest -q` to confirm.

- [ ] **Step 8: Commit**

```bash
git add routes/teams.py routes/__init__.py templates/team_dashboard.html templates/bar_dashboard.html tests/test_team_routes.py
git -c commit.gpgsign=false commit -m "teams: create team from bar dashboard, gated on sponsorship"
```

---

## Task 5: Roster add/remove

**Files:**
- Modify: `routes/teams.py`
- Test: `tests/test_team_routes.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_team_routes.py`:

```python
from models import PlayerProfile, TeamMembership


def _team_with_profile(app):
    creator, sponsor, bar, league = _seed_bar_and_league(app)
    team = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                created_by_id=creator.id, created_at=datetime.utcnow())
    db.session.add(team)
    db.session.flush()
    profile = PlayerProfile(first_name='Pat', last_name='Smith', league_id=league.id)
    db.session.add(profile)
    db.session.commit()
    return creator, sponsor, bar, league, team, profile


def test_add_to_roster(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        tid, pid = team.id, profile.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/team/{tid}/roster/add', data={'profile_id': str(pid)})
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.filter_by(team_id=tid, profile_id=pid).first()
        assert m is not None


def test_remove_from_roster(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        m = TeamMembership(team_id=team.id, profile_id=profile.id)
        db.session.add(m)
        db.session.commit()
        tid, mid = team.id, m.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/remove')
    assert resp.status_code == 302
    with app.app_context():
        assert TeamMembership.query.get(mid) is None


def test_outsider_cannot_modify_roster(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        outsider = _create_user('roster_out')
        tid, pid = team.id, profile.id
    client = app.test_client()
    _login(client, 'roster_out')
    resp = client.post(f'/team/{tid}/roster/add', data={'profile_id': str(pid)})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_team_routes.py -k roster -v`
Expected: 404s.

- [ ] **Step 3: Add the routes**

Append to `routes/teams.py`:

```python
@bp.route('/team/<int:tid>/roster/add', methods=['POST'])
@login_required
def roster_add(tid):
    from models import PlayerProfile, TeamMembership
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    profile_id = request.form.get('profile_id', type=int)
    if not profile_id:
        flash('Pick a player.', 'danger')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    profile = PlayerProfile.query.get_or_404(profile_id)
    if profile.league_id != team.league_id:
        flash('Player is not in this league.', 'danger')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    if TeamMembership.query.filter_by(team_id=tid, profile_id=profile_id).first():
        flash(f'{profile.full_name} is already on this team.', 'warning')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    db.session.add(TeamMembership(team_id=tid, profile_id=profile_id))
    db.session.commit()
    flash(f'{profile.full_name} added to roster.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))


@bp.route('/team/<int:tid>/roster/<int:mid>/remove', methods=['POST'])
@login_required
def roster_remove(tid, mid):
    from models import TeamMembership
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)
    db.session.delete(m)
    db.session.commit()
    flash('Removed from roster.', 'info')
    return redirect(url_for('teams.team_dashboard', tid=tid))
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_team_routes.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/teams.py tests/test_team_routes.py
git -c commit.gpgsign=false commit -m "teams: roster add and remove (Bar Staff only)"
```

---

## Task 6: Roster UI on team dashboard

**Files:**
- Modify: `templates/team_dashboard.html`
- Modify: `routes/teams.py` (pass roster + invitable players to template)

- [ ] **Step 1: Update team_dashboard route**

In `routes/teams.py`, replace the `team_dashboard` view:

```python
@bp.route('/team/<int:tid>')
@login_required
def team_dashboard(tid):
    from models import PlayerProfile, TeamMembership
    team = Team.query.get_or_404(tid)
    if not (team.can_manage_roster(current_user) or team.is_member(current_user)):
        abort(403)
    roster = TeamMembership.query.filter_by(team_id=tid).all()
    rostered_profile_ids = [m.profile_id for m in roster]
    if rostered_profile_ids:
        invitable = PlayerProfile.query.filter(
            PlayerProfile.league_id == team.league_id,
            ~PlayerProfile.id.in_(rostered_profile_ids),
        ).order_by(PlayerProfile.first_name, PlayerProfile.last_name).all()
    else:
        invitable = PlayerProfile.query.filter_by(league_id=team.league_id).order_by(
            PlayerProfile.first_name, PlayerProfile.last_name
        ).all()
    return render_template('team_dashboard.html', team=team,
                           roster=roster, invitable=invitable,
                           can_manage=team.can_manage_roster(current_user),
                           can_assign_sk=team.can_assign_scorekeeper(current_user))
```

- [ ] **Step 2: Replace `templates/team_dashboard.html`**

```html
{% extends 'base.html' %}
{% block title %}{{ team.name }} — TourneyTracker{% endblock %}
{% block content %}
<header class="page-hero">
  <div>
    <h1 class="page-hero__title">{{ team.name }}</h1>
    <p class="page-hero__sub">{{ team.bar.name }} · {{ team.league.name }}</p>
  </div>
</header>

<section class="admin-block">
  <div class="section-head">
    <h2 class="section-head__title">Roster</h2>
    <span class="section-head__count">{{ roster|length }}</span>
  </div>
  {% if roster %}
    <ul class="sponsors-list">
      {% for m in roster %}
        <li>
          <strong>{{ m.profile.full_name }}</strong>
          {% if m.is_captain %}<span class="badge">Captain</span>{% endif %}
          {% if m.is_co_captain %}<span class="badge">Co-Captain</span>{% endif %}
          {% if m.is_scorekeeper %}<span class="badge">Scorekeeper</span>{% endif %}
          {% if m.is_sub %}<span class="badge muted">Sub</span>{% endif %}
          {% if can_manage %}
            <form method="post" action="{{ url_for('teams.roster_role', tid=team.id, mid=m.id) }}" style="display:inline">
              <button name="role" value="captain" class="btn btn-link">{{ 'Demote' if m.is_captain else 'Make Captain' }}</button>
              <button name="role" value="co_captain" class="btn btn-link">{{ 'Demote' if m.is_co_captain else 'Make Co-Captain' }}</button>
              <button name="role" value="sub" class="btn btn-link">{{ 'Unsub' if m.is_sub else 'Mark Sub' }}</button>
            </form>
          {% endif %}
          {% if can_assign_sk %}
            <form method="post" action="{{ url_for('teams.roster_scorekeeper', tid=team.id, mid=m.id) }}" style="display:inline">
              <button class="btn btn-link">{{ 'Revoke Scorekeeper' if m.is_scorekeeper else 'Make Scorekeeper' }}</button>
            </form>
          {% endif %}
          {% if can_manage %}
            <form method="post" action="{{ url_for('teams.roster_remove', tid=team.id, mid=m.id) }}" style="display:inline">
              <button class="btn btn-link btn-danger">Remove</button>
            </form>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">No players on the roster yet.</p>
  {% endif %}

  {% if can_manage and invitable %}
    <form method="post" action="{{ url_for('teams.roster_add', tid=team.id) }}" class="form-stack form-stack--inline">
      <select name="profile_id" class="form-control" required>
        <option value="">Pick a player…</option>
        {% for p in invitable %}
          <option value="{{ p.id }}">{{ p.full_name }}</option>
        {% endfor %}
      </select>
      <button class="btn btn-primary">Add to roster</button>
    </form>
  {% endif %}
</section>
{% endblock %}
```

(The `roster_role` and `roster_scorekeeper` routes are added in Tasks 7 and 8. Stub them now to avoid `BuildError`:)

In `routes/teams.py`, append:

```python
@bp.route('/team/<int:tid>/roster/<int:mid>/role', methods=['POST'])
@login_required
def roster_role(tid, mid):
    abort(404)


@bp.route('/team/<int:tid>/roster/<int:mid>/scorekeeper', methods=['POST'])
@login_required
def roster_scorekeeper(tid, mid):
    abort(404)
```

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: all green (no new tests added in this task; existing roster tests still pass).

- [ ] **Step 4: Commit**

```bash
git add routes/teams.py templates/team_dashboard.html
git -c commit.gpgsign=false commit -m "teams: render roster and add stubs for role routes"
```

---

## Task 7: Captain/Co-Captain/Sub role toggling (with inline account creation)

**Files:**
- Modify: `routes/teams.py` (replace `roster_role` stub)
- Create: `templates/inline_account_create.html`
- Test: `tests/test_team_routes.py` (extend), `tests/test_team_account_creation.py`

- [ ] **Step 1: Failing tests for direct toggle (existing user_id)**

Append to `tests/test_team_routes.py`:

```python
def test_make_sub_no_account_needed(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        m = TeamMembership(team_id=team.id, profile_id=profile.id)
        db.session.add(m)
        db.session.commit()
        tid, mid = team.id, m.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={'role': 'sub'})
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.get(mid)
        assert m.is_sub is True


def test_make_captain_with_existing_user_id(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        existing_user = _create_user('existing_player')
        profile.user_id = existing_user.id
        m = TeamMembership(team_id=team.id, profile_id=profile.id)
        db.session.add(m)
        db.session.commit()
        tid, mid = team.id, m.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={'role': 'captain'})
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.get(mid)
        assert m.is_captain is True
```

- [ ] **Step 2: Failing tests for inline account creation**

Create `tests/test_team_account_creation.py`:

```python
from datetime import datetime
from app import db
from models import (User, Bar, BarMembership, League, LeagueSponsorship,
                    Team, TeamMembership, PlayerProfile)


def _create_user(username, password='secret123', **flags):
    u = User(username=username,
             is_admin=flags.get('is_admin', False),
             is_league_operator=flags.get('is_league_operator', False))
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password='secret123'):
    return client.post('/login', data={'username': username, 'password': password})


def _seed(app):
    creator = _create_user('ac_creator', is_admin=True)
    sponsor = _create_user('ac_sponsor')
    bar = Bar(name='Cactus', created_by_id=creator.id, created_at=datetime.utcnow())
    league = League(name='WSPA', owner_id=creator.id)
    db.session.add_all([bar, league])
    db.session.flush()
    db.session.add(BarMembership(user_id=sponsor.id, bar_id=bar.id, is_primary=True))
    db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                     invited_by_id=creator.id,
                                     invited_at=datetime.utcnow()))
    team = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                created_by_id=creator.id, created_at=datetime.utcnow())
    db.session.add(team)
    db.session.flush()
    profile = PlayerProfile(first_name='New', last_name='Captain', league_id=league.id)
    db.session.add(profile)
    db.session.flush()
    db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
    db.session.commit()
    return team.id, TeamMembership.query.first().id


def test_captain_toggle_without_user_id_renders_interstitial(app):
    with app.app_context():
        tid, mid = _seed(app)
    client = app.test_client()
    _login(client, 'ac_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={'role': 'captain'})
    assert resp.status_code == 200
    assert b'Create login for' in resp.data


def test_interstitial_submit_creates_user_and_assigns_role(app):
    with app.app_context():
        tid, mid = _seed(app)
    client = app.test_client()
    _login(client, 'ac_sponsor')
    # Step 1: trigger the interstitial
    client.post(f'/team/{tid}/roster/{mid}/role', data={'role': 'captain'})
    # Step 2: submit credentials
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={
        'role': 'captain',
        'create_account': '1',
        'username': 'new.captain',
        'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = User.query.filter_by(username='new.captain').first()
        assert u is not None
        m = TeamMembership.query.get(mid)
        assert m.is_captain is True
        assert m.profile.user_id == u.id


def test_interstitial_duplicate_username_re_renders(app):
    with app.app_context():
        tid, mid = _seed(app)
        # Pre-existing user with the same username
        _create_user('taken_name')
    client = app.test_client()
    _login(client, 'ac_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={
        'role': 'captain',
        'create_account': '1',
        'username': 'taken_name',
        'password': 'secret123',
    })
    assert resp.status_code == 200
    assert b'already taken' in resp.data
    with app.app_context():
        m = TeamMembership.query.get(mid)
        assert m.is_captain is False
```

- [ ] **Step 3: Run and confirm failure**

Run: `pytest tests/test_team_routes.py -k role tests/test_team_account_creation.py -v`
Expected: 5 failures (404 from stub).

- [ ] **Step 4: Replace the `roster_role` stub**

In `routes/teams.py`, replace the `roster_role` stub with:

```python
@bp.route('/team/<int:tid>/roster/<int:mid>/role', methods=['POST'])
@login_required
def roster_role(tid, mid):
    from models import TeamMembership, User
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)
    role = request.form.get('role', '')
    if role == 'sub':
        m.is_sub = not m.is_sub
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))
    if role not in ('captain', 'co_captain'):
        abort(400)

    flag_attr = 'is_captain' if role == 'captain' else 'is_co_captain'
    setting_to = not getattr(m, flag_attr)
    if not setting_to:
        # Demoting — never needs an account.
        setattr(m, flag_attr, False)
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))

    # Promoting. Need a user account on the profile.
    if m.profile.user_id is None:
        if request.form.get('create_account') != '1':
            return render_template('inline_account_create.html',
                                   team=team, m=m, role=role,
                                   error=None)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or len(password) < 6:
            return render_template('inline_account_create.html',
                                   team=team, m=m, role=role,
                                   error='Username and 6+ char password required.')
        if User.query.filter_by(username=username).first():
            return render_template('inline_account_create.html',
                                   team=team, m=m, role=role,
                                   error=f'Username "{username}" is already taken.')
        new_user = User(username=username, is_admin=False, is_league_operator=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()
        m.profile.user_id = new_user.id

    setattr(m, flag_attr, True)
    db.session.commit()
    flash(f'{m.profile.full_name} promoted to {role.replace("_", " ").title()}.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))
```

- [ ] **Step 5: Create `templates/inline_account_create.html`**

```html
{% extends 'base.html' %}
{% block title %}Create login — TourneyTracker{% endblock %}
{% block content %}
<header class="page-hero">
  <h1 class="page-hero__title">Create login for {{ m.profile.full_name }}</h1>
  <p class="page-hero__sub">{{ team.name }} · {{ role.replace('_', ' ').title() }}</p>
</header>

{% if error %}<p class="alert alert-danger">{{ error }}</p>{% endif %}

<p>Promoting this player to <strong>{{ role.replace('_', ' ').title() }}</strong> requires a login. Pick a username and password to share with them out-of-band.</p>

<form method="post" action="{{ url_for('teams.roster_role', tid=team.id, mid=m.id) }}" class="form-stack">
  <input type="hidden" name="role" value="{{ role }}">
  <input type="hidden" name="create_account" value="1">
  <div class="form-field">
    <label class="form-label">Username</label>
    <input type="text" name="username" class="form-control" required
           value="{{ (m.profile.first_name + '.' + m.profile.last_name)|lower }}">
  </div>
  <div class="form-field">
    <label class="form-label">Password (6+ chars)</label>
    <input type="password" name="password" class="form-control" required minlength="6">
  </div>
  <button class="btn btn-primary">Create and assign role</button>
  <a href="{{ url_for('teams.team_dashboard', tid=team.id) }}" class="btn btn-link">Cancel</a>
</form>
{% endblock %}
```

- [ ] **Step 6: Run and confirm pass**

Run: `pytest tests/test_team_routes.py tests/test_team_account_creation.py -v`
Expected: all PASS.

Full suite green.

- [ ] **Step 7: Commit**

```bash
git add routes/teams.py templates/inline_account_create.html tests/test_team_routes.py tests/test_team_account_creation.py
git -c commit.gpgsign=false commit -m "teams: captain/co-captain toggling with inline account creation"
```

---

## Task 8: Scorekeeper toggling (Captain/Co-Captain power, also inline account creation)

**Files:**
- Modify: `routes/teams.py` (replace `roster_scorekeeper` stub)
- Test: `tests/test_team_routes.py`, `tests/test_team_account_creation.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_team_routes.py`:

```python
def test_captain_assigns_scorekeeper(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        captain_user = _create_user('cap_user')
        profile.user_id = captain_user.id
        cap_m = TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True)
        db.session.add(cap_m)
        # Another player to make scorekeeper
        p2 = PlayerProfile(first_name='SK', last_name='Player', league_id=league.id)
        sk_user = _create_user('sk_user')
        p2.user_id = sk_user.id
        db.session.add(p2)
        db.session.flush()
        sk_m = TeamMembership(team_id=team.id, profile_id=p2.id)
        db.session.add(sk_m)
        db.session.commit()
        tid, mid = team.id, sk_m.id
    client = app.test_client()
    _login(client, 'cap_user')
    resp = client.post(f'/team/{tid}/roster/{mid}/scorekeeper')
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.get(mid)
        assert m.is_scorekeeper is True


def test_random_player_cannot_assign_scorekeeper(app):
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        plain = _create_user('plain_player')
        m = TeamMembership(team_id=team.id, profile_id=profile.id)
        db.session.add(m)
        db.session.commit()
        tid, mid = team.id, m.id
    client = app.test_client()
    _login(client, 'plain_player')
    resp = client.post(f'/team/{tid}/roster/{mid}/scorekeeper')
    assert resp.status_code == 403
```

Append to `tests/test_team_account_creation.py`:

```python
def test_scorekeeper_inline_account_creation(app):
    with app.app_context():
        tid, mid = _seed(app)
        # Captain has a user; the player getting scorekeeper does not.
        m = TeamMembership.query.get(mid)
        captain_user = _create_user('ac_captain_login')
        m.profile.user_id = captain_user.id
        m.is_captain = True
        # Add a second player without user_id
        from models import TeamMembership as TM
        p2 = PlayerProfile(first_name='Side', last_name='Kick',
                           league_id=Team.query.get(tid).league_id)
        db.session.add(p2)
        db.session.flush()
        sk_m = TM(team_id=tid, profile_id=p2.id)
        db.session.add(sk_m)
        db.session.commit()
        sk_mid = sk_m.id
    client = app.test_client()
    _login(client, 'ac_captain_login')
    resp = client.post(f'/team/{tid}/roster/{sk_mid}/scorekeeper')
    assert resp.status_code == 200
    assert b'Create login for' in resp.data

    resp = client.post(f'/team/{tid}/roster/{sk_mid}/scorekeeper', data={
        'create_account': '1',
        'username': 'side.kick',
        'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.get(sk_mid)
        assert m.is_scorekeeper is True
        assert m.profile.user_id is not None
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_team_routes.py tests/test_team_account_creation.py -v`
Expected: 3 new failures (404 from stub).

- [ ] **Step 3: Replace the `roster_scorekeeper` stub**

In `routes/teams.py`, replace the stub:

```python
@bp.route('/team/<int:tid>/roster/<int:mid>/scorekeeper', methods=['POST'])
@login_required
def roster_scorekeeper(tid, mid):
    from models import TeamMembership, User
    team = Team.query.get_or_404(tid)
    if not team.can_assign_scorekeeper(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)

    setting_to = not m.is_scorekeeper
    if not setting_to:
        m.is_scorekeeper = False
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))

    # Promoting to scorekeeper. Need a user account.
    if m.profile.user_id is None:
        if request.form.get('create_account') != '1':
            return render_template('inline_account_create.html',
                                   team=team, m=m, role='scorekeeper',
                                   error=None)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or len(password) < 6:
            return render_template('inline_account_create.html',
                                   team=team, m=m, role='scorekeeper',
                                   error='Username and 6+ char password required.')
        if User.query.filter_by(username=username).first():
            return render_template('inline_account_create.html',
                                   team=team, m=m, role='scorekeeper',
                                   error=f'Username "{username}" is already taken.')
        new_user = User(username=username, is_admin=False, is_league_operator=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()
        m.profile.user_id = new_user.id

    m.is_scorekeeper = True
    db.session.commit()
    flash(f'{m.profile.full_name} can now keep score.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_team_routes.py tests/test_team_account_creation.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/teams.py tests/test_team_routes.py tests/test_team_account_creation.py
git -c commit.gpgsign=false commit -m "teams: scorekeeper toggling (captain power) with inline account creation"
```

---

## Task 9: My Teams page

**Files:**
- Modify: `routes/teams.py`
- Create: `templates/my_teams.html`
- Modify: `templates/base.html`
- Test: `tests/test_my_teams.py`

- [ ] **Step 1: Failing test**

Create `tests/test_my_teams.py`:

```python
from datetime import datetime
from app import db
from models import (User, Bar, BarMembership, League, LeagueSponsorship,
                    Team, TeamMembership, PlayerProfile)


def _create_user(username, **flags):
    u = User(username=username, is_admin=flags.get('is_admin', False))
    u.set_password('secret123')
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password='secret123'):
    return client.post('/login', data={'username': username, 'password': password})


def test_my_teams_lists_user_teams(app):
    with app.app_context():
        admin = _create_user('mt_admin', is_admin=True)
        bar = Bar(name='B', created_by_id=admin.id, created_at=datetime.utcnow())
        league = League(name='L', owner_id=admin.id)
        db.session.add_all([bar, league])
        db.session.flush()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        team = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                    created_by_id=admin.id, created_at=datetime.utcnow())
        db.session.add(team)
        db.session.flush()

        member = _create_user('mt_member')
        profile = PlayerProfile(first_name='M', last_name='Member',
                                league_id=league.id, user_id=member.id)
        db.session.add(profile)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        db.session.commit()
    client = app.test_client()
    _login(client, 'mt_member')
    resp = client.get('/my-teams')
    assert resp.status_code == 200
    assert b'Cactus A' in resp.data


def test_my_teams_excludes_other_users_teams(app):
    with app.app_context():
        admin = _create_user('mt2_admin', is_admin=True)
        bar = Bar(name='B', created_by_id=admin.id, created_at=datetime.utcnow())
        league = League(name='L', owner_id=admin.id)
        db.session.add_all([bar, league])
        db.session.flush()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        team = Team(name='Other Team', bar_id=bar.id, league_id=league.id,
                    created_by_id=admin.id, created_at=datetime.utcnow())
        db.session.add(team)
        db.session.flush()
        # Other user is on the team; current user isn't
        other_user = _create_user('mt2_other')
        profile = PlayerProfile(first_name='O', last_name='Other',
                                league_id=league.id, user_id=other_user.id)
        db.session.add(profile)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        # Current user has no profile linked
        plain = _create_user('mt2_plain')
        db.session.commit()
    client = app.test_client()
    _login(client, 'mt2_plain')
    resp = client.get('/my-teams')
    assert resp.status_code == 200
    assert b'Other Team' not in resp.data
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_my_teams.py -v`
Expected: 404.

- [ ] **Step 3: Add the route**

Append to `routes/teams.py`:

```python
@bp.route('/my-teams')
@login_required
def my_teams():
    from models import PlayerProfile, TeamMembership
    profiles = PlayerProfile.query.filter_by(user_id=current_user.id).all()
    profile_ids = [p.id for p in profiles]
    if profile_ids:
        memberships = TeamMembership.query.filter(
            TeamMembership.profile_id.in_(profile_ids)
        ).all()
    else:
        memberships = []
    return render_template('my_teams.html', memberships=memberships)
```

- [ ] **Step 4: Create `templates/my_teams.html`**

```html
{% extends 'base.html' %}
{% block title %}My Teams — TourneyTracker{% endblock %}
{% block content %}
<header class="page-hero">
  <h1 class="page-hero__title">My Teams</h1>
</header>

{% if memberships %}
  <ul class="sponsors-list">
    {% for m in memberships %}
      <li>
        <a href="{{ url_for('teams.team_dashboard', tid=m.team_id) }}">{{ m.team.name }}</a>
        <span class="muted">{{ m.team.league.name }} · {{ m.team.bar.name }}</span>
        {% if m.is_captain %}<span class="badge">Captain</span>{% endif %}
        {% if m.is_co_captain %}<span class="badge">Co-Captain</span>{% endif %}
        {% if m.is_scorekeeper %}<span class="badge">Scorekeeper</span>{% endif %}
        {% if m.is_sub %}<span class="badge muted">Sub</span>{% endif %}
      </li>
    {% endfor %}
  </ul>
{% else %}
  <p class="muted">You're not on any teams yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Add the nav link to `templates/base.html`**

Inside the authenticated nav section:

```html
{% if current_user.is_authenticated %}
  {% set my_profiles = current_user.profiles if current_user.profiles is defined else [] %}
  <a href="{{ url_for('teams.my_teams') }}">My Teams</a>
{% endif %}
```

(Showing it for any authenticated user is fine — empty state handles non-members.)

- [ ] **Step 6: Run and confirm pass**

Run: `pytest tests/test_my_teams.py -v`
Expected: 2 PASS.

Full suite green.

- [ ] **Step 7: Commit**

```bash
git add routes/teams.py templates/my_teams.html templates/base.html tests/test_my_teams.py
git -c commit.gpgsign=false commit -m "teams: add /my-teams page"
```

---

## Task 10: Final integration and smoke test

- [ ] Run full test suite: `pytest -q` — should be all green.
- [ ] Boot app: `FLASK_DEBUG=1 /home/flip/tourneytracker/.venv/bin/python app.py`
- [ ] Browser walkthrough:
  1. Log in as admin, go to a sponsored bar's dashboard.
  2. Create a team; pick a sponsored league.
  3. From the team dashboard, add 3 players to the roster.
  4. Promote one to Captain (without `user_id` — should show interstitial; create login).
  5. Log out, log in as the new captain → "My Teams" shows the team with the Captain badge.
  6. Captain promotes another teammate to Scorekeeper → interstitial fires for that player too.
  7. Verify partial unique constraints by trying to set a second Captain — gets a flash error.

---

## Self-review checklist

- [x] Team table created with bar_id, league_id, FK to user.id (Task 1)
- [x] TeamMembership with role flags + partial uniques on captain/co-captain (Task 2)
- [x] `Team.can_manage_roster`, `can_assign_scorekeeper`, `is_member` + `auth_helpers.can_create_team` (Task 3)
- [x] Team creation gated on sponsorship (Task 4)
- [x] Roster add/remove (Task 5)
- [x] Roster UI with role buttons (Task 6)
- [x] Captain/Co-Captain/Sub toggle with inline account creation (Task 7)
- [x] Scorekeeper toggle with inline account creation (Task 8)
- [x] /my-teams page (Task 9)
- [x] Smoke test (Task 10)
