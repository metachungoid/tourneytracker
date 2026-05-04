# Roles and Sponsor/Bar Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `Admin → User` with two new boolean capability flags, introduce `Bar`, `BarMembership`, and `LeagueSponsorship` tables, extend tournament authorization to admit Bar Staff for bar-owned recreational tournaments, and add an admin Bars panel, league Sponsors panel, and a per-Bar dashboard with staff management and bar-tournament creation.

**Architecture:** Keep the existing inline migration approach (a list of `ALTER TABLE`/`CREATE TABLE` statements wrapped in try/except inside `app.py`). Add a one-time pre-`create_all()` step to rename `admin → user` for environments holding the old table. New auth predicates live in a new `auth_helpers.py` module. New routes live in a new `routes/bars.py` blueprint. `Tournament.can_manage` is extended in-place rather than replaced.

**Tech Stack:** Flask, SQLAlchemy, Flask-Login, SQLite (production database), pytest (in-memory SQLite for tests), Werkzeug password hashing, Jinja templates.

---

## File Structure

**New files:**
- `auth_helpers.py` — global capability predicates (`can_create_league`, `can_create_bar`, `can_promote_user`, `can_act_as_sponsor`).
- `routes/bars.py` — Blueprint for the per-Bar dashboard, staff invite/remove, and recreational tournament creation.
- `templates/bar_dashboard.html` — single-bar dashboard page.
- `templates/bar_form.html` — onboard-new-bar form fragment included from the league dashboard.
- `tests/test_user_capabilities.py`
- `tests/test_bar_membership.py`
- `tests/test_league_sponsorship.py`
- `tests/test_migration_admin_to_user.py`
- `tests/test_bar_tournaments.py`
- `tests/test_sponsor_routes.py` — end-to-end route tests for sponsor onboarding flows.

**Modified files:**
- `models.py` — rename `Admin → User`; replace `role` derivations with `is_admin`/`is_league_operator` columns; add `Bar`, `BarMembership`, `LeagueSponsorship` models; add `PlayerProfile.user_id`; add `Tournament.bar_id`; extend `Tournament.can_manage`.
- `app.py` — pre-`create_all()` rename hook; new entries in the migration `ALTER TABLE` list; default-admin bootstrap updated.
- `routes/__init__.py` — register the new `bars` blueprint.
- `routes/admin.py` — replace single `role` field with two checkboxes; gate league/bar creation.
- `routes/leagues.py` — gate `new_league` on `can_create_league`; new sponsor management routes (`add_sponsor`, `onboard_sponsor`, `remove_sponsor`).
- `routes/tournaments.py` — accept `bar_id` for new bar-owned tournaments; reject "both league_id and bar_id"; redirect bar-owned tournaments back to the bar dashboard after delete.
- `routes/auth.py` — login redirect priority: leagues → bars → public landing.
- `templates/admin.html` — role checkboxes; new Bars list section.
- `templates/league_dashboard.html` — Sponsors panel and Add Sponsor form.
- `templates/base.html` — add a "My Bar" nav entry visible to users with a `BarMembership`.
- `tests/conftest.py` — update `_get_or_create_test_league` and any `Admin(...)` constructions to use `User` with boolean flags.

**Test discipline:** every functional task starts with a failing test, then minimal implementation, then a passing run, then a commit. Migration tasks include an explicit pre-implementation "fail first" assertion against the old schema.

---

## Task 1: Bootstrap fixtures for User model rename

**Files:**
- Modify: `tests/conftest.py`
- Modify: `models.py`

This task introduces the `User` class as an alias of `Admin` so tests can begin importing `User` while production code is migrated piecemeal. Field semantics are unchanged here — pure aliasing — so no migration is needed yet.

- [ ] **Step 1: Write a failing import test**

Create `tests/test_user_alias.py`:

```python
def test_user_is_importable_from_models():
    from models import User, Admin
    assert User is Admin
```

- [ ] **Step 2: Run it and confirm failure**

Run: `pytest tests/test_user_alias.py -v`
Expected: `ImportError` because `User` does not exist in `models`.

- [ ] **Step 3: Add the alias in `models.py`**

At the end of `models.py`, add:

```python
# Transitional alias — Task 11 renames Admin to User and removes this line.
User = Admin
```

- [ ] **Step 4: Run the test and confirm pass**

Run: `pytest tests/test_user_alias.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_user_alias.py
git commit -m "models: introduce transitional User alias for Admin"
```

---

## Task 2: Add `is_league_operator` boolean column to Admin (parallel to `role`)

**Files:**
- Modify: `models.py:19-37`
- Modify: `app.py:53-65`
- Test: `tests/test_user_capabilities.py`

We add the new column alongside the existing `role` so we can write capability predicates against both at once, then drop `role` later (Task 11).

- [ ] **Step 1: Write the failing capability test**

Create `tests/test_user_capabilities.py`:

```python
from app import db
from models import Admin


def test_admin_flag_grants_admin_capability(app):
    with app.app_context():
        u = Admin(username='boss', is_admin=True, is_league_operator=False)
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        assert u.is_admin is True
        assert u.is_league_operator is False


def test_operator_flag_persists(app):
    with app.app_context():
        u = Admin(username='op', is_admin=False, is_league_operator=True)
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        fetched = Admin.query.filter_by(username='op').first()
        assert fetched.is_admin is False
        assert fetched.is_league_operator is True


def test_neither_flag_is_default(app):
    with app.app_context():
        u = Admin(username='plain')
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        fetched = Admin.query.filter_by(username='plain').first()
        assert fetched.is_admin is False
        assert fetched.is_league_operator is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_user_capabilities.py -v`
Expected: FAIL — either `TypeError: 'is_admin' is an invalid keyword argument` (because `is_admin` is currently a property, not a column) or attribute mismatch.

- [ ] **Step 3: Replace the `is_admin`/`is_manager` properties with columns**

In `models.py`, replace the existing `Admin` class body (lines 19–37) with:

```python
class Admin(db.Model, UserMixin):
    __tablename__ = 'admin'  # renamed to 'user' in Task 11
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='admin')  # legacy, dropped in Task 11
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_league_operator = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)
```

Note: removing the `is_admin` and `is_manager` *properties* in favor of *columns* is intentional — every existing use of `current_user.is_admin` continues to work because attribute access is identical.

- [ ] **Step 4: Add the columns to the migration block in `app.py`**

In `app.py`, inside the `with app.app_context():` block, add to the existing `col_sql` list (after the existing `ADD COLUMN role` line):

```python
"ALTER TABLE admin ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0",
"ALTER TABLE admin ADD COLUMN is_league_operator BOOLEAN NOT NULL DEFAULT 0",
"UPDATE admin SET is_admin = 1 WHERE role = 'admin' AND is_admin = 0",
"UPDATE admin SET is_league_operator = 1 WHERE role = 'manager' AND is_league_operator = 0",
```

- [ ] **Step 5: Update `routes/admin.py` to set the new flags on user creation**

In `routes/admin.py:42-62`, inside `admin_add_user`, after `a = Admin(username=username, role=role)` and before `db.session.add(a)`, add:

```python
    a.is_admin = (role == 'admin')
    a.is_league_operator = (role == 'manager')
```

- [ ] **Step 6: Update default-admin bootstrap**

In `app.py:41-47`, inside `create_default_admin`, change the new admin construction to:

```python
def create_default_admin():
    if not Admin.query.filter_by(username='admin').first():
        a = Admin(username='admin', role='admin', is_admin=True, is_league_operator=False)
        a.set_password('admin123')
        db.session.add(a)
        db.session.commit()
        print('Default admin created  →  username: admin  /  password: admin123')
```

- [ ] **Step 7: Update `tests/conftest.py` test admin creation**

In `tests/conftest.py:34-39`, change the test admin construction to:

```python
        admin = Admin(username='testadmin', role='admin',
                      is_admin=True, is_league_operator=False)
        admin.set_password('test123')
```

- [ ] **Step 8: Run the new tests and the full suite**

Run: `pytest tests/test_user_capabilities.py -v`
Expected: PASS (3 tests).

Run: `pytest -v`
Expected: All tests pass. Existing gating/advancement/clear tests should be unaffected.

- [ ] **Step 9: Commit**

```bash
git add models.py app.py routes/admin.py tests/conftest.py tests/test_user_capabilities.py
git commit -m "models: add is_admin and is_league_operator columns alongside role"
```

---

## Task 3: Global capability predicates in `auth_helpers.py`

**Files:**
- Create: `auth_helpers.py`
- Test: `tests/test_user_capabilities.py` (extend)

- [ ] **Step 1: Add failing tests for the predicates**

Append to `tests/test_user_capabilities.py`:

```python
from auth_helpers import can_create_league, can_create_bar, can_promote_user


def _make_user(is_admin=False, is_league_operator=False, username='u'):
    u = Admin(username=username, role='admin' if is_admin else 'manager',
              is_admin=is_admin, is_league_operator=is_league_operator)
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def test_can_create_league_admin(app):
    with app.app_context():
        u = _make_user(is_admin=True, username='a')
        assert can_create_league(u) is True


def test_can_create_league_operator(app):
    with app.app_context():
        u = _make_user(is_league_operator=True, username='op')
        assert can_create_league(u) is True


def test_can_create_league_neither_denied(app):
    with app.app_context():
        u = _make_user(username='plain')
        assert can_create_league(u) is False


def test_can_create_league_anonymous(app):
    from flask_login import AnonymousUserMixin
    with app.app_context():
        assert can_create_league(AnonymousUserMixin()) is False


def test_can_create_bar_matches_create_league(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='ba')
        op = _make_user(is_league_operator=True, username='bo')
        plain = _make_user(username='bp')
        assert can_create_bar(admin) is True
        assert can_create_bar(op) is True
        assert can_create_bar(plain) is False


def test_can_promote_user_admin_only(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='pa')
        op = _make_user(is_league_operator=True, username='po')
        assert can_promote_user(admin) is True
        assert can_promote_user(op) is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_user_capabilities.py -v`
Expected: `ImportError: cannot import name 'can_create_league' from 'auth_helpers'`.

- [ ] **Step 3: Create `auth_helpers.py`**

```python
"""Authorization predicates not naturally tied to a single model.

Model-attached predicates (League.can_manage, Tournament.can_manage,
Bar.can_manage) live on their respective models.  This module covers
global capabilities and cross-model checks (e.g., Sponsorship.can_act).
"""


def _is_real_user(user):
    """True only for an authenticated User row (not anonymous)."""
    return bool(user and getattr(user, 'is_authenticated', False))


def can_create_league(user):
    if not _is_real_user(user):
        return False
    return bool(user.is_admin or user.is_league_operator)


def can_create_bar(user):
    if not _is_real_user(user):
        return False
    return bool(user.is_admin or user.is_league_operator)


def can_promote_user(user):
    """Only admins can flip is_league_operator on another user."""
    if not _is_real_user(user):
        return False
    return bool(user.is_admin)
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_user_capabilities.py -v`
Expected: All tests in this file pass.

- [ ] **Step 5: Commit**

```bash
git add auth_helpers.py tests/test_user_capabilities.py
git commit -m "auth: add can_create_league, can_create_bar, can_promote_user"
```

---

## Task 4: Bar model and table

**Files:**
- Modify: `models.py` (append)
- Modify: `app.py` (migration list)
- Test: `tests/test_bar_membership.py`

- [ ] **Step 1: Write a failing model test**

Create `tests/test_bar_membership.py`:

```python
from datetime import datetime
from app import db
from models import Admin, Bar


def _make_admin(username='admin1'):
    u = Admin(username=username, role='admin', is_admin=True)
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def test_bar_creation_persists(app):
    with app.app_context():
        creator = _make_admin('creator')
        bar = Bar(name='Cactus', address='123 Main St', phone='555-1212',
                  created_by_id=creator.id, created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.commit()
        fetched = Bar.query.filter_by(name='Cactus').first()
        assert fetched is not None
        assert fetched.address == '123 Main St'
        assert fetched.phone == '555-1212'
        assert fetched.created_by_id == creator.id
        assert fetched.created_at is not None


def test_bar_name_required(app):
    with app.app_context():
        from sqlalchemy.exc import IntegrityError
        bar = Bar(name=None, created_by_id=None)
        db.session.add(bar)
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_bar_membership.py -v`
Expected: `ImportError: cannot import name 'Bar' from 'models'`.

- [ ] **Step 3: Add the `Bar` model**

Append to `models.py` (after the `Tournament` class, before `Participant`):

```python
class Bar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('Admin', foreign_keys=[created_by_id])
    memberships = db.relationship(
        'BarMembership', backref='bar', lazy=True, cascade='all, delete-orphan'
    )
    sponsorships = db.relationship(
        'LeagueSponsorship', backref='bar', lazy=True, cascade='all, delete-orphan'
    )
    tournaments = db.relationship('Tournament', backref='bar', lazy=True)
```

(The `BarMembership`, `LeagueSponsorship`, and `Tournament.bar` relationships are added in Tasks 5, 6, and 8. Adding the backref strings now is cheap and makes the later additions touch fewer lines.)

- [ ] **Step 4: Add the table-create entry**

In `app.py`, append to the `col_sql` migration list:

```python
"""CREATE TABLE IF NOT EXISTS bar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(120) NOT NULL,
    address VARCHAR(200),
    phone VARCHAR(30),
    created_by_id INTEGER REFERENCES admin(id),
    created_at TIMESTAMP
)""",
```

(`db.create_all()` would also create the table. The explicit `CREATE TABLE IF NOT EXISTS` keeps the migration block self-documenting and tolerates partial-state environments.)

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_bar_membership.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_bar_membership.py
git commit -m "models: add Bar entity"
```

---

## Task 5: BarMembership with primary uniqueness

**Files:**
- Modify: `models.py`
- Modify: `app.py` (migration list)
- Test: `tests/test_bar_membership.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_bar_membership.py`:

```python
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from models import BarMembership


def _make_bar(creator=None):
    if creator is None:
        creator = _make_admin('barmaker')
    bar = Bar(name='Cactus', created_by_id=creator.id, created_at=datetime.utcnow())
    db.session.add(bar)
    db.session.commit()
    return bar


def test_user_bar_unique(app):
    with app.app_context():
        u = _make_admin('u1')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # Second membership for same (user, bar) must fail.
        db.session.add(BarMembership(user_id=u.id, bar_id=bar.id, is_primary=False))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_primary_per_bar(app):
    with app.app_context():
        u1 = _make_admin('m1')
        u2 = _make_admin('m2')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u1.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # A second is_primary=True for the same bar must fail.
        db.session.add(BarMembership(user_id=u2.id, bar_id=bar.id, is_primary=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_many_non_primary_allowed(app):
    with app.app_context():
        u1 = _make_admin('s1')
        u2 = _make_admin('s2')
        u3 = _make_admin('s3')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u1.id, bar_id=bar.id, is_primary=True))
        db.session.add(BarMembership(user_id=u2.id, bar_id=bar.id, is_primary=False))
        db.session.add(BarMembership(user_id=u3.id, bar_id=bar.id, is_primary=False))
        db.session.commit()
        assert BarMembership.query.filter_by(bar_id=bar.id).count() == 3
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_bar_membership.py -v`
Expected: 3 new tests fail with `ImportError: cannot import name 'BarMembership'`.

- [ ] **Step 3: Add the `BarMembership` model**

In `models.py`, append (after `Bar`):

```python
class BarMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    bar_id = db.Column(db.Integer, db.ForeignKey('bar.id'), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship('Admin', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'bar_id', name='uq_bar_membership_user_bar'),
        db.Index('uq_bar_membership_primary', 'bar_id',
                 unique=True, sqlite_where=db.text('is_primary = 1')),
    )
```

The partial unique index is SQLite-specific via `sqlite_where`. SQLAlchemy emits `CREATE UNIQUE INDEX ... WHERE is_primary = 1` for SQLite, which enforces "at most one primary per bar."

- [ ] **Step 4: Add migration entry**

Append to the `col_sql` list in `app.py`:

```python
"""CREATE TABLE IF NOT EXISTS bar_membership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES admin(id),
    bar_id INTEGER NOT NULL REFERENCES bar(id),
    is_primary BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE (user_id, bar_id)
)""",
"CREATE UNIQUE INDEX IF NOT EXISTS uq_bar_membership_primary ON bar_membership (bar_id) WHERE is_primary = 1",
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_bar_membership.py -v`
Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_bar_membership.py
git commit -m "models: add BarMembership with primary uniqueness"
```

---

## Task 6: LeagueSponsorship model

**Files:**
- Modify: `models.py`
- Modify: `app.py` (migration list)
- Test: `tests/test_league_sponsorship.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_league_sponsorship.py`:

```python
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app import db
from models import Admin, Bar, League, LeagueSponsorship


def _seed(app):
    admin = Admin(username='ls_admin', role='admin', is_admin=True)
    admin.set_password('x' * 6)
    db.session.add(admin)
    db.session.flush()
    league = League(name='WSPA Marinette', owner_id=admin.id)
    db.session.add(league)
    db.session.flush()
    bar = Bar(name='Cactus', created_by_id=admin.id, created_at=datetime.utcnow())
    db.session.add(bar)
    db.session.commit()
    return admin, league, bar


def test_sponsorship_persists(app):
    with app.app_context():
        admin, league, bar = _seed(app)
        ls = LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                               invited_by_id=admin.id,
                               invited_at=datetime.utcnow())
        db.session.add(ls)
        db.session.commit()
        fetched = LeagueSponsorship.query.first()
        assert fetched.league_id == league.id
        assert fetched.bar_id == bar.id


def test_sponsorship_unique_per_league_bar(app):
    with app.app_context():
        admin, league, bar = _seed(app)
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_league_sponsorship.py -v`
Expected: `ImportError: cannot import name 'LeagueSponsorship'`.

- [ ] **Step 3: Add the model**

In `models.py`, append (after `BarMembership`):

```python
class LeagueSponsorship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    bar_id = db.Column(db.Integer, db.ForeignKey('bar.id'), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    invited_at = db.Column(db.DateTime, nullable=True)

    league = db.relationship('League', foreign_keys=[league_id], backref='sponsorships')
    inviter = db.relationship('Admin', foreign_keys=[invited_by_id])

    __table_args__ = (
        db.UniqueConstraint('league_id', 'bar_id', name='uq_league_sponsorship'),
    )
```

- [ ] **Step 4: Add migration entry**

Append to `app.py` `col_sql`:

```python
"""CREATE TABLE IF NOT EXISTS league_sponsorship (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id INTEGER NOT NULL REFERENCES league(id),
    bar_id INTEGER NOT NULL REFERENCES bar(id),
    invited_by_id INTEGER REFERENCES admin(id),
    invited_at TIMESTAMP,
    UNIQUE (league_id, bar_id)
)""",
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_league_sponsorship.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_league_sponsorship.py
git commit -m "models: add LeagueSponsorship"
```

---

## Task 7: Reserved column `PlayerProfile.user_id`

**Files:**
- Modify: `models.py:88-93`
- Modify: `app.py` (migration list)
- Test: `tests/test_user_capabilities.py` (extend)

- [ ] **Step 1: Failing test**

Append to `tests/test_user_capabilities.py`:

```python
from models import PlayerProfile


def test_player_profile_user_id_optional(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='pp_admin')
        from models import League
        league = League(name='L', owner_id=admin.id)
        db.session.add(league)
        db.session.flush()
        # Without user_id
        p1 = PlayerProfile(first_name='Anon', last_name='', league_id=league.id)
        # With user_id linking back to a user
        p2 = PlayerProfile(first_name='Linked', last_name='', league_id=league.id,
                           user_id=admin.id)
        db.session.add_all([p1, p2])
        db.session.commit()
        assert PlayerProfile.query.filter_by(first_name='Anon').first().user_id is None
        assert PlayerProfile.query.filter_by(first_name='Linked').first().user_id == admin.id
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_user_capabilities.py::test_player_profile_user_id_optional -v`
Expected: `TypeError: 'user_id' is an invalid keyword argument for PlayerProfile`.

- [ ] **Step 3: Add the column to the model**

In `models.py:88-93`, inside `PlayerProfile`, after the `league_id` column declaration, add:

```python
    user_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
```

- [ ] **Step 4: Add migration entry**

Append to `app.py` `col_sql`:

```python
"ALTER TABLE player_profile ADD COLUMN user_id INTEGER REFERENCES admin(id)",
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_user_capabilities.py -v`
Expected: All tests in file PASS.

- [ ] **Step 6: Commit**

```bash
git add models.py app.py tests/test_user_capabilities.py
git commit -m "models: reserve PlayerProfile.user_id for player logins"
```

---

## Task 8: `Tournament.bar_id` and `Tournament.can_manage` extension

**Files:**
- Modify: `models.py:139-180`
- Modify: `app.py` (migration list)
- Test: `tests/test_bar_tournaments.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_bar_tournaments.py`:

```python
from datetime import datetime
from app import db
from models import Admin, Bar, BarMembership, League, Tournament


def _admin(username, **flags):
    u = Admin(username=username, role='admin', **flags)
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def _bar(creator):
    b = Bar(name=f'B-{creator.username}', created_by_id=creator.id,
            created_at=datetime.utcnow())
    db.session.add(b)
    db.session.commit()
    return b


def _league(owner):
    l = League(name=f'L-{owner.username}', owner_id=owner.id)
    db.session.add(l)
    db.session.commit()
    return l


def test_bar_tournament_persists_with_bar_id(app):
    with app.app_context():
        creator = _admin('bt1', is_admin=True)
        bar = _bar(creator)
        t = Tournament(name='Friday Night', bar_id=bar.id, owner_id=creator.id)
        db.session.add(t)
        db.session.commit()
        fetched = Tournament.query.first()
        assert fetched.bar_id == bar.id
        assert fetched.league_id is None


def test_can_manage_admin(app):
    with app.app_context():
        admin = _admin('bt2', is_admin=True)
        bar = _bar(admin)
        t = Tournament(name='X', bar_id=bar.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(admin) is True


def test_can_manage_bar_primary(app):
    with app.app_context():
        creator = _admin('bt3', is_admin=True)
        bar = _bar(creator)
        primary = _admin('primary')
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id, is_primary=True))
        t = Tournament(name='X', bar_id=bar.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(primary) is True


def test_can_manage_bar_staff(app):
    with app.app_context():
        creator = _admin('bt4', is_admin=True)
        bar = _bar(creator)
        staff = _admin('staff')
        db.session.add(BarMembership(user_id=staff.id, bar_id=bar.id, is_primary=False))
        t = Tournament(name='X', bar_id=bar.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(staff) is True


def test_can_manage_outsider_denied(app):
    with app.app_context():
        creator = _admin('bt5', is_admin=True)
        bar = _bar(creator)
        outsider = _admin('outsider')
        t = Tournament(name='X', bar_id=bar.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(outsider) is False


def test_can_manage_league_path_unchanged(app):
    with app.app_context():
        owner = _admin('bt6', is_admin=False, is_league_operator=True)
        league = _league(owner)
        t = Tournament(name='X', league_id=league.id, owner_id=owner.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(owner) is True


def test_can_manage_legacy_owner_id_path(app):
    with app.app_context():
        owner = _admin('bt7')
        # No bar_id, no league_id — pure legacy tournament.
        t = Tournament(name='X', owner_id=owner.id)
        db.session.add(t)
        db.session.commit()
        assert t.can_manage(owner) is True
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_bar_tournaments.py -v`
Expected: failures — `'bar_id' is an invalid keyword argument` and the can_manage tests fail because the bar path doesn't exist.

- [ ] **Step 3: Add the column and the relationship**

In `models.py`, inside the `Tournament` class (around line 144 next to `league_id`), add:

```python
    bar_id = db.Column(db.Integer, db.ForeignKey('bar.id'), nullable=True)
```

- [ ] **Step 4: Extend `can_manage`**

Replace `Tournament.can_manage` (lines 172–179) with:

```python
    def can_manage(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        if self.league_id and self.league:
            return self.league.can_manage(user)
        if self.bar_id and self.bar:
            return self.bar.can_manage(user)
        return self.owner_id == user.id
```

- [ ] **Step 5: Add `Bar.can_manage` (needed by the check above)**

In `models.py`, inside the `Bar` class added in Task 4, add:

```python
    def can_manage(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        return BarMembership.query.filter_by(
            bar_id=self.id, user_id=user.id
        ).first() is not None

    def can_manage_staff(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        m = BarMembership.query.filter_by(bar_id=self.id, user_id=user.id).first()
        return bool(m and m.is_primary)
```

- [ ] **Step 6: Add migration entry**

Append to `app.py` `col_sql`:

```python
"ALTER TABLE tournament ADD COLUMN bar_id INTEGER REFERENCES bar(id)",
```

- [ ] **Step 7: Run and confirm pass**

Run: `pytest tests/test_bar_tournaments.py -v`
Expected: 7 PASS.

Run: `pytest -v`
Expected: full suite green.

- [ ] **Step 8: Commit**

```bash
git add models.py app.py tests/test_bar_tournaments.py
git commit -m "models: add Tournament.bar_id and extend can_manage for bar tournaments"
```

---

## Task 9: `Sponsorship.can_act` predicate

**Files:**
- Modify: `auth_helpers.py`
- Test: `tests/test_league_sponsorship.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_league_sponsorship.py`:

```python
from auth_helpers import can_act_as_sponsor
from models import BarMembership


def _seed_full(app):
    admin, league, bar = _seed(app)
    sponsor = Admin(username='spons', role='manager', is_admin=False)
    sponsor.set_password('x' * 6)
    db.session.add(sponsor)
    db.session.flush()
    db.session.add(BarMembership(user_id=sponsor.id, bar_id=bar.id, is_primary=True))
    db.session.commit()
    return admin, league, bar, sponsor


def test_can_act_requires_membership_and_sponsorship(app):
    with app.app_context():
        admin, league, bar, sponsor = _seed_full(app)
        # No LeagueSponsorship row yet → cannot act.
        assert can_act_as_sponsor(sponsor, league, bar) is False


def test_can_act_with_membership_and_sponsorship(app):
    with app.app_context():
        admin, league, bar, sponsor = _seed_full(app)
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        assert can_act_as_sponsor(sponsor, league, bar) is True


def test_can_act_admin_always_true(app):
    with app.app_context():
        admin, league, bar, sponsor = _seed_full(app)
        # Admin can act even without a sponsorship row.
        assert can_act_as_sponsor(admin, league, bar) is True


def test_can_act_no_membership_denied(app):
    with app.app_context():
        admin, league, bar, _ = _seed_full(app)
        outsider = Admin(username='outsider', role='manager')
        outsider.set_password('x' * 6)
        db.session.add(outsider)
        db.session.commit()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        assert can_act_as_sponsor(outsider, league, bar) is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_league_sponsorship.py -v`
Expected: `ImportError: cannot import name 'can_act_as_sponsor'`.

- [ ] **Step 3: Implement the predicate**

In `auth_helpers.py`, append:

```python
def can_act_as_sponsor(user, league, bar):
    """True if `user` is a member of `bar` AND `bar` sponsors `league`.

    Admins always pass. Used (in later projects) for any sponsor action
    scoped to a specific league context — creating teams, designating
    tournament officials, etc.
    """
    if not _is_real_user(user):
        return False
    if user.is_admin:
        return True
    if not bar.can_manage(user):
        return False
    from models import LeagueSponsorship
    return LeagueSponsorship.query.filter_by(
        league_id=league.id, bar_id=bar.id
    ).first() is not None
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_league_sponsorship.py -v`
Expected: 6 PASS (2 from Task 6 + 4 here).

- [ ] **Step 5: Commit**

```bash
git add auth_helpers.py tests/test_league_sponsorship.py
git commit -m "auth: add can_act_as_sponsor sponsorship predicate"
```

---

## Task 10: Gate league creation on `can_create_league`

**Files:**
- Modify: `routes/leagues.py:23-36`
- Test: `tests/test_sponsor_routes.py`

- [ ] **Step 1: Write a failing route test**

Create `tests/test_sponsor_routes.py`:

```python
from app import db
from models import Admin


def _create_user(username, password='secret123', **flags):
    u = Admin(username=username, role='admin' if flags.get('is_admin') else 'manager', **flags)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password='secret123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)


def test_plain_user_cannot_create_league(app):
    with app.app_context():
        _create_user('plain', is_admin=False, is_league_operator=False)
    client = app.test_client()
    _login(client, 'plain')
    resp = client.post('/league/new', data={'name': 'Forbidden'})
    assert resp.status_code == 403


def test_operator_can_create_league(app):
    with app.app_context():
        _create_user('op', is_league_operator=True)
    client = app.test_client()
    _login(client, 'op')
    resp = client.post('/league/new', data={'name': 'OK League'},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        from models import League
        assert League.query.filter_by(name='OK League').first() is not None


def test_admin_can_create_league(app):
    with app.app_context():
        _create_user('admin1', is_admin=True)
    client = app.test_client()
    _login(client, 'admin1')
    resp = client.post('/league/new', data={'name': 'Admin League'},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        from models import League
        assert League.query.filter_by(name='Admin League').first() is not None
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py::test_plain_user_cannot_create_league -v`
Expected: FAIL — currently `/league/new` succeeds for any logged-in user.

- [ ] **Step 3: Add the gate**

In `routes/leagues.py:23-36`, replace:

```python
@bp.route('/league/new', methods=['GET', 'POST'])
@login_required
def new_league():
    if request.method == 'POST':
```

with:

```python
@bp.route('/league/new', methods=['GET', 'POST'])
@login_required
def new_league():
    from auth_helpers import can_create_league
    if not can_create_league(current_user):
        abort(403)
    if request.method == 'POST':
```

- [ ] **Step 4: Run all three tests and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/leagues.py tests/test_sponsor_routes.py
git commit -m "routes: gate league creation on can_create_league"
```

---

## Task 11: Replace role dropdown with checkboxes; drop `role` column

**Files:**
- Modify: `routes/admin.py:42-62`
- Modify: `templates/admin.html` (the Add user form section)
- Modify: `models.py` (drop `role` column and the `User = Admin` alias becomes the canonical name)
- Modify: `app.py` (drop migration entry; rename to `user`)
- Modify: `tests/conftest.py`
- Test: `tests/test_migration_admin_to_user.py`, `tests/test_user_capabilities.py`

This is the riskiest task. It (a) renames the table from `admin` → `user`, (b) drops the `role` column after backfilling, and (c) cleans up code paths that still reference `role` or the `User = Admin` alias.

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_migration_admin_to_user.py`:

```python
"""Verify the admin → user rename and role drop migration.

Strategy: start a fresh in-memory engine, build the OLD schema by hand,
populate it, then run the migration helper and assert the resulting
schema matches what the new model expects.
"""
import pytest
from sqlalchemy import create_engine, text, inspect


@pytest.fixture
def old_db():
    """An in-memory SQLite with the pre-migration schema."""
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(80) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'admin'
            )
        """))
        conn.execute(text(
            "INSERT INTO admin (username, password_hash, role) "
            "VALUES ('alice', 'h', 'admin'), ('bob', 'h', 'manager')"
        ))
    return engine


def test_migration_renames_table_and_backfills(old_db):
    from app_migrations import migrate_admin_to_user
    migrate_admin_to_user(old_db)
    insp = inspect(old_db)
    assert 'user' in insp.get_table_names()
    assert 'admin' not in insp.get_table_names()
    cols = {c['name'] for c in insp.get_columns('user')}
    assert 'role' not in cols
    assert 'is_admin' in cols
    assert 'is_league_operator' in cols
    with old_db.begin() as conn:
        rows = conn.execute(text(
            "SELECT username, is_admin, is_league_operator FROM user ORDER BY username"
        )).fetchall()
    assert rows == [('alice', 1, 0), ('bob', 0, 1)]
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_migration_admin_to_user.py -v`
Expected: `ModuleNotFoundError: app_migrations`.

- [ ] **Step 3: Create `app_migrations.py` with the rename helper**

Create `app_migrations.py`:

```python
"""One-shot schema migrations runnable independently of Flask startup.

Used in production via `app.py`'s startup path AND directly by tests
that need to assert migration behavior.
"""
from sqlalchemy import inspect, text


def migrate_admin_to_user(engine):
    """Rename `admin` to `user`, backfill the boolean flags, drop `role`.

    Idempotent: safe to run when `user` already exists or when the
    boolean columns are already present.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    with engine.begin() as conn:
        # 1. Rename the table if needed.
        if 'admin' in tables and 'user' not in tables:
            conn.execute(text('ALTER TABLE admin RENAME TO user'))
            tables.discard('admin')
            tables.add('user')

        if 'user' not in tables:
            return  # fresh install — db.create_all will build it from the model

        # 2. Add the new columns if missing.
        cols = {c['name'] for c in insp.get_columns('user')}
        if 'is_admin' not in cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
        if 'is_league_operator' not in cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN is_league_operator BOOLEAN NOT NULL DEFAULT 0"))

        # 3. Backfill from `role` if it still exists.
        cols = {c['name'] for c in inspect(engine).get_columns('user')}
        if 'role' in cols:
            conn.execute(text("UPDATE user SET is_admin = 1 WHERE role = 'admin'"))
            conn.execute(text(
                "UPDATE user SET is_league_operator = 1 WHERE role = 'manager'"
            ))
            # 4. Drop the role column. SQLite ≥3.35 supports DROP COLUMN.
            conn.execute(text("ALTER TABLE user DROP COLUMN role"))
```

- [ ] **Step 4: Run the migration test and confirm pass**

Run: `pytest tests/test_migration_admin_to_user.py -v`
Expected: 1 PASS.

- [ ] **Step 5: Wire the migration into `app.py` startup**

In `app.py`, replace the body of `with app.app_context():` (lines 50–109) with:

```python
with app.app_context():
    from app_migrations import migrate_admin_to_user
    migrate_admin_to_user(db.engine)
    db.create_all()
    # Additive ALTER TABLEs — safe to re-run.
    for col_sql in [
        "ALTER TABLE tournament ADD COLUMN bracket_type VARCHAR(10) DEFAULT 'single'",
        "ALTER TABLE tournament ADD COLUMN lb_format VARCHAR(20) DEFAULT 'bestof'",
        "ALTER TABLE tournament ADD COLUMN lb_race_to INTEGER DEFAULT 1",
        "ALTER TABLE tournament ADD COLUMN owner_id INTEGER REFERENCES user(id)",
        "ALTER TABLE tournament ADD COLUMN bar_id INTEGER REFERENCES bar(id)",
        "ALTER TABLE player_profile ADD COLUMN first_name VARCHAR(50)",
        "ALTER TABLE player_profile ADD COLUMN last_name VARCHAR(50)",
        "ALTER TABLE player_profile ADD COLUMN league_id INTEGER REFERENCES league(id)",
        "ALTER TABLE player_profile ADD COLUMN user_id INTEGER REFERENCES user(id)",
        "CREATE TABLE IF NOT EXISTS league (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(100) NOT NULL, owner_id INTEGER NOT NULL REFERENCES user(id))",
        "ALTER TABLE tournament ADD COLUMN league_id INTEGER REFERENCES league(id)",
        "ALTER TABLE manager_share ADD COLUMN league_id INTEGER REFERENCES league(id)",
        """CREATE TABLE IF NOT EXISTS bar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(120) NOT NULL,
            address VARCHAR(200),
            phone VARCHAR(30),
            created_by_id INTEGER REFERENCES user(id),
            created_at TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS bar_membership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES user(id),
            bar_id INTEGER NOT NULL REFERENCES bar(id),
            is_primary BOOLEAN NOT NULL DEFAULT 0,
            UNIQUE (user_id, bar_id)
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bar_membership_primary ON bar_membership (bar_id) WHERE is_primary = 1",
        """CREATE TABLE IF NOT EXISTS league_sponsorship (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_id INTEGER NOT NULL REFERENCES league(id),
            bar_id INTEGER NOT NULL REFERENCES bar(id),
            invited_by_id INTEGER REFERENCES user(id),
            invited_at TIMESTAMP,
            UNIQUE (league_id, bar_id)
        )""",
    ]:
        try:
            db.session.execute(db.text(col_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Migrate legacy name → first_name + last_name (unchanged from before)
    from models import PlayerProfile, League, ManagerShare
    for p in PlayerProfile.query.filter(
        PlayerProfile.first_name.is_(None),
        PlayerProfile.name.isnot(None),
    ).all():
        parts = p.name.strip().split(None, 1)
        p.first_name = parts[0]
        p.last_name = parts[1] if len(parts) > 1 else ''
    db.session.commit()

    # Default-league migration (unchanged from before, but reads `User`)
    from models import User, Tournament
    if League.query.count() == 0:
        owner_ids = {t.owner_id for t in Tournament.query.filter(
            Tournament.owner_id.isnot(None)
        ).all()}
        for u in User.query.filter_by(is_league_operator=True).all():
            owner_ids.add(u.id)
        if not owner_ids:
            admin_user = User.query.filter_by(is_admin=True).first()
            if admin_user:
                owner_ids.add(admin_user.id)
        for oid in owner_ids:
            owner = db.session.get(User, oid)
            league = League(name=f"{owner.username}'s League", owner_id=oid)
            db.session.add(league)
            db.session.flush()
            Tournament.query.filter_by(owner_id=oid).update({'league_id': league.id})
        first_league = League.query.first()
        if first_league:
            Tournament.query.filter(Tournament.league_id.is_(None)).update({'league_id': first_league.id})
            PlayerProfile.query.filter(PlayerProfile.league_id.is_(None)).update({'league_id': first_league.id})
        for share in ManagerShare.query.filter(ManagerShare.league_id.is_(None)).all():
            league = League.query.filter_by(owner_id=share.owner_id).first()
            if league:
                share.league_id = league.id
        db.session.commit()

    create_default_admin()
```

- [ ] **Step 6: Rename `Admin` → `User` in the model and update all FK targets**

In `models.py`:

1. Rename the class `Admin` → `User`. Update `__tablename__ = 'admin'` to `__tablename__ = 'user'`.
2. Drop the legacy `role` column declaration.
3. Replace the `User = Admin` alias at the end of the file with `Admin = User` (keeps existing imports working during transition; remove in a follow-up).
4. Update every `db.ForeignKey('admin.id')` reference to `db.ForeignKey('user.id')`. Targets: `League.owner_id`, `ManagerShare.owner_id`, `ManagerShare.delegate_id`, `Tournament.owner_id`, `PlayerProfile.user_id`, `Bar.created_by_id`, `BarMembership.user_id`, `LeagueSponsorship.invited_by_id`.

After edits, the `User` class declaration looks like:

```python
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_league_operator = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


# Legacy alias — kept for one release, removed once all imports updated.
Admin = User
```

And the `load_user` user_loader becomes:

```python
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
```

`get_user_leagues` continues to work since it doesn't reference `Admin` directly except via `User.query`.

- [ ] **Step 7: Replace the role dropdown in `templates/admin.html`**

Find the existing `<select name="role">` block (it lives in the "Add user" form, near the top of the admin grid). Replace it with two checkboxes:

```html
<div class="form-field">
  <label class="form-checkbox">
    <input type="checkbox" name="is_admin" value="1">
    <span>Admin</span>
  </label>
  <label class="form-checkbox">
    <input type="checkbox" name="is_league_operator" value="1">
    <span>League Operator</span>
  </label>
  <p class="form-help">Either, both, or neither. Operators can create leagues; admins can do anything.</p>
</div>
```

- [ ] **Step 8: Update `routes/admin.py` to read the checkboxes**

Replace `admin_add_user` (lines 40–62) with:

```python
@bp.route('/admin/add_user', methods=['POST'])
@admin_required
def admin_add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin_flag = request.form.get('is_admin') == '1'
    is_op_flag = request.form.get('is_league_operator') == '1'
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    a = Admin(username=username, is_admin=is_admin_flag,
              is_league_operator=is_op_flag)
    a.set_password(password)
    db.session.add(a)
    db.session.commit()
    label = 'Admin' if is_admin_flag else ('League Operator' if is_op_flag else 'User')
    flash(f'{label} "{username}" created.', 'success')
    return redirect(url_for('admin.admin_panel'))
```

- [ ] **Step 9: Add a route test for the checkbox flow**

Append to `tests/test_sponsor_routes.py`:

```python
def test_admin_creates_user_with_both_flags(app):
    with app.app_context():
        _create_user('boss', is_admin=True)
    client = app.test_client()
    _login(client, 'boss')
    resp = client.post('/admin/add_user', data={
        'username': 'dual', 'password': 'secret123',
        'is_admin': '1', 'is_league_operator': '1',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='dual').first()
        assert u.is_admin is True
        assert u.is_league_operator is True


def test_admin_creates_user_with_neither_flag(app):
    with app.app_context():
        _create_user('boss2', is_admin=True)
    client = app.test_client()
    _login(client, 'boss2')
    resp = client.post('/admin/add_user', data={
        'username': 'plain1', 'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='plain1').first()
        assert u.is_admin is False
        assert u.is_league_operator is False
```

- [ ] **Step 10: Update `tests/conftest.py`**

Replace lines 34–39 with:

```python
        admin = Admin(username='testadmin', is_admin=True, is_league_operator=False)
        admin.set_password('test123')
```

- [ ] **Step 11: Run the full test suite**

Run: `pytest -v`
Expected: every test passes — migration test, capability tests, bar tests, sponsor route tests, the existing gating/advancement/clear tests.

- [ ] **Step 12: Commit**

```bash
git add models.py app.py app_migrations.py routes/admin.py templates/admin.html tests/conftest.py tests/test_migration_admin_to_user.py tests/test_sponsor_routes.py
git commit -m "models: rename admin→user, drop role, add checkbox UI"
```

---

## Task 12: Sponsors panel + remove sponsor on the league dashboard

**Files:**
- Modify: `routes/leagues.py`
- Modify: `templates/league_dashboard.html`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
from datetime import datetime
from models import Admin, Bar, League, LeagueSponsorship


def _seed_league_with_sponsor(app):
    op = _create_user('lop', is_league_operator=True)
    league = League(name='LX', owner_id=op.id)
    bar = Bar(name='Cactus', created_by_id=op.id, created_at=datetime.utcnow())
    db.session.add_all([league, bar])
    db.session.flush()
    ls = LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                           invited_by_id=op.id, invited_at=datetime.utcnow())
    db.session.add(ls)
    db.session.commit()
    return op, league, bar, ls


def test_dashboard_lists_sponsor(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        lid = league.id
    client = app.test_client()
    _login(client, 'lop')
    resp = client.get(f'/league/{lid}')
    assert resp.status_code == 200
    assert b'Cactus' in resp.data


def test_remove_sponsor(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        lid, sid = league.id, ls.id
    client = app.test_client()
    _login(client, 'lop')
    resp = client.post(f'/league/{lid}/sponsor/{sid}/remove')
    assert resp.status_code == 302
    with app.app_context():
        assert LeagueSponsorship.query.get(sid) is None
        # Bar still exists.
        assert Bar.query.first() is not None


def test_remove_sponsor_requires_league_management(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        outsider = _create_user('outsider')
        lid, sid = league.id, ls.id
    client = app.test_client()
    _login(client, 'outsider')
    resp = client.post(f'/league/{lid}/sponsor/{sid}/remove')
    assert resp.status_code == 403
    with app.app_context():
        assert LeagueSponsorship.query.get(sid) is not None
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k sponsor -v`
Expected: failures — route doesn't exist; template missing.

- [ ] **Step 3: Add the remove-sponsor route**

In `routes/leagues.py`, append:

```python
@bp.route('/league/<int:lid>/sponsor/<int:sid>/remove', methods=['POST'])
@login_required
def remove_sponsor(lid, sid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    ls = LeagueSponsorship.query.get_or_404(sid)
    if ls.league_id != lid:
        abort(404)
    db.session.delete(ls)
    db.session.commit()
    flash('Sponsor removed from league.', 'info')
    return redirect(url_for('leagues.league_dashboard', lid=lid))
```

Add the import at the top: `from models import LeagueSponsorship`.

- [ ] **Step 4: Pass sponsorships to the template**

In `routes/leagues.py:39-49`, update `league_dashboard`:

```python
@bp.route('/league/<int:lid>')
@login_required
def league_dashboard(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    tournaments = Tournament.query.filter_by(league_id=lid).order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()
    player_count = PlayerProfile.query.filter_by(league_id=lid).count()
    sponsorships = LeagueSponsorship.query.filter_by(league_id=lid).all()
    return render_template('league_dashboard.html', league=league,
                           tournaments=tournaments, player_count=player_count,
                           sponsorships=sponsorships)
```

- [ ] **Step 5: Render the panel in the template**

In `templates/league_dashboard.html`, add a new section near the bottom of the dashboard grid:

```html
<section class="admin-block">
  <div class="section-head">
    <h2 class="section-head__title">Sponsors</h2>
    <span class="section-head__count">{{ sponsorships|length }}</span>
  </div>
  {% if sponsorships %}
    <ul class="sponsors-list">
      {% for ls in sponsorships %}
        <li class="sponsors-list__item">
          <span class="sponsors-list__name">{{ ls.bar.name }}</span>
          {% set primary = ls.bar.memberships|selectattr('is_primary')|first %}
          {% if primary %}
            <span class="sponsors-list__primary">{{ primary.user.username }}</span>
          {% endif %}
          <form method="post"
                action="{{ url_for('leagues.remove_sponsor', lid=league.id, sid=ls.id) }}"
                style="display:inline">
            <button type="submit" class="btn btn-link btn-danger">Remove</button>
          </form>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">No sponsors yet.</p>
  {% endif %}
</section>
```

- [ ] **Step 6: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k sponsor -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add routes/leagues.py templates/league_dashboard.html tests/test_sponsor_routes.py
git commit -m "leagues: render sponsors panel and add remove-sponsor action"
```

---

## Task 13: Onboard new Bar from the league dashboard

**Files:**
- Modify: `routes/leagues.py`
- Modify: `templates/league_dashboard.html`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
from models import BarMembership


def test_onboard_new_bar_creates_full_chain(app):
    with app.app_context():
        op = _create_user('onb_op', is_league_operator=True)
        league = League(name='LO', owner_id=op.id)
        db.session.add(league)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'onb_op')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'Cactus',
        'sponsor_username': 'cactus_owner',
        'sponsor_password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        bar = Bar.query.filter_by(name='Cactus').first()
        assert bar is not None
        u = Admin.query.filter_by(username='cactus_owner').first()
        assert u is not None
        assert u.is_admin is False
        assert u.is_league_operator is False
        m = BarMembership.query.filter_by(user_id=u.id, bar_id=bar.id).first()
        assert m is not None
        assert m.is_primary is True
        ls = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bar.id).first()
        assert ls is not None


def test_onboard_rejects_duplicate_username(app):
    with app.app_context():
        op = _create_user('dup_op', is_league_operator=True)
        league = League(name='LD', owner_id=op.id)
        db.session.add(league)
        # An existing user with this username already exists.
        existing = Admin(username='taken')
        existing.set_password('x' * 6)
        db.session.add(existing)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'dup_op')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'Other',
        'sponsor_username': 'taken',
        'sponsor_password': 'secret123',
    }, follow_redirects=True)
    # Redirect back to dashboard with an error flash; no bar created.
    with app.app_context():
        assert Bar.query.filter_by(name='Other').first() is None


def test_onboard_requires_league_management(app):
    with app.app_context():
        op = _create_user('o3_op', is_league_operator=True)
        outsider = _create_user('o3_out')
        league = League(name='L3', owner_id=op.id)
        db.session.add(league)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'o3_out')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'X', 'sponsor_username': 'x', 'sponsor_password': 'secret123',
    })
    assert resp.status_code == 403
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k onboard -v`
Expected: 404s — route doesn't exist.

- [ ] **Step 3: Add the route**

In `routes/leagues.py`, append:

```python
@bp.route('/league/<int:lid>/sponsor/onboard', methods=['POST'])
@login_required
def onboard_sponsor(lid):
    from datetime import datetime
    from models import Admin, Bar, BarMembership
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    bar_name = request.form.get('bar_name', '').strip()
    username = request.form.get('sponsor_username', '').strip()
    password = request.form.get('sponsor_password', '')
    if not bar_name or not username or len(password) < 6:
        flash('Bar name, username, and a 6+ character password are required.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))

    bar = Bar(name=bar_name, created_by_id=current_user.id,
              created_at=datetime.utcnow())
    db.session.add(bar)
    db.session.flush()

    user = Admin(username=username, is_admin=False, is_league_operator=False)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    db.session.add(BarMembership(user_id=user.id, bar_id=bar.id, is_primary=True))
    db.session.add(LeagueSponsorship(league_id=lid, bar_id=bar.id,
                                     invited_by_id=current_user.id,
                                     invited_at=datetime.utcnow()))
    db.session.commit()
    flash(f'Sponsor "{bar_name}" onboarded with primary login "{username}".', 'success')
    return redirect(url_for('leagues.league_dashboard', lid=lid))
```

- [ ] **Step 4: Add the form to the template**

In `templates/league_dashboard.html`, inside the Sponsors section added in Task 12, append a form:

```html
<form method="post"
      action="{{ url_for('leagues.onboard_sponsor', lid=league.id) }}"
      class="form-stack form-stack--inline">
  <h3>Onboard new bar sponsor</h3>
  <input type="text" name="bar_name" class="form-control" placeholder="Bar name" required>
  <input type="text" name="sponsor_username" class="form-control" placeholder="Primary sponsor username" required>
  <input type="password" name="sponsor_password" class="form-control" placeholder="Password (6+ chars)" minlength="6" required>
  <button type="submit" class="btn btn-primary">Create sponsor</button>
</form>
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k onboard -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add routes/leagues.py templates/league_dashboard.html tests/test_sponsor_routes.py
git commit -m "leagues: onboard new bar with primary sponsor in one transaction"
```

---

## Task 14: Invite existing Bar to a league

**Files:**
- Modify: `routes/leagues.py`
- Modify: `templates/league_dashboard.html`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
def test_invite_existing_bar(app):
    with app.app_context():
        op = _create_user('inv_op', is_league_operator=True)
        league = League(name='LI', owner_id=op.id)
        bar = Bar(name='Existing', created_by_id=op.id,
                  created_at=datetime.utcnow())
        db.session.add_all([league, bar])
        db.session.commit()
        lid, bid = league.id, bar.id
    client = app.test_client()
    _login(client, 'inv_op')
    resp = client.post(f'/league/{lid}/sponsor/invite', data={'bar_id': bid})
    assert resp.status_code == 302
    with app.app_context():
        ls = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bid).first()
        assert ls is not None


def test_invite_duplicate_rejected(app):
    with app.app_context():
        op = _create_user('inv2_op', is_league_operator=True)
        league = League(name='LI2', owner_id=op.id)
        bar = Bar(name='Existing2', created_by_id=op.id,
                  created_at=datetime.utcnow())
        db.session.add_all([league, bar])
        db.session.flush()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=op.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        lid, bid = league.id, bar.id
    client = app.test_client()
    _login(client, 'inv2_op')
    resp = client.post(f'/league/{lid}/sponsor/invite', data={'bar_id': bid},
                       follow_redirects=False)
    # Should redirect with a flash, not crash. Only one row exists.
    assert resp.status_code == 302
    with app.app_context():
        rows = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bid).all()
        assert len(rows) == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k invite -v`
Expected: 404s — route doesn't exist.

- [ ] **Step 3: Add the invite route**

In `routes/leagues.py`, append:

```python
@bp.route('/league/<int:lid>/sponsor/invite', methods=['POST'])
@login_required
def invite_sponsor(lid):
    from datetime import datetime
    from models import Bar
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    bar_id = request.form.get('bar_id', type=int)
    if not bar_id:
        flash('Pick a bar to invite.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    bar = Bar.query.get_or_404(bar_id)
    existing = LeagueSponsorship.query.filter_by(
        league_id=lid, bar_id=bar.id
    ).first()
    if existing:
        flash(f'{bar.name} already sponsors this league.', 'warning')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    db.session.add(LeagueSponsorship(
        league_id=lid, bar_id=bar.id,
        invited_by_id=current_user.id, invited_at=datetime.utcnow(),
    ))
    db.session.commit()
    flash(f'{bar.name} added as a sponsor.', 'success')
    return redirect(url_for('leagues.league_dashboard', lid=lid))
```

- [ ] **Step 4: Add the form to the template**

In `templates/league_dashboard.html`, alongside the onboard form added in Task 13, add:

```html
<form method="post"
      action="{{ url_for('leagues.invite_sponsor', lid=league.id) }}"
      class="form-stack form-stack--inline">
  <h3>Invite existing bar</h3>
  <select name="bar_id" class="form-control" required>
    <option value="">Pick a bar…</option>
    {% for b in invitable_bars %}
      <option value="{{ b.id }}">{{ b.name }}</option>
    {% endfor %}
  </select>
  <button type="submit" class="btn btn-secondary">Invite</button>
</form>
```

- [ ] **Step 5: Pass `invitable_bars` to the template**

In `routes/leagues.py:39-49`, update `league_dashboard` to compute the list:

```python
@bp.route('/league/<int:lid>')
@login_required
def league_dashboard(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    tournaments = Tournament.query.filter_by(league_id=lid).order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()
    player_count = PlayerProfile.query.filter_by(league_id=lid).count()
    sponsorships = LeagueSponsorship.query.filter_by(league_id=lid).all()
    sponsored_bar_ids = [s.bar_id for s in sponsorships]
    from models import Bar
    invitable_bars = Bar.query.filter(~Bar.id.in_(sponsored_bar_ids)).order_by(Bar.name).all() \
        if sponsored_bar_ids else Bar.query.order_by(Bar.name).all()
    return render_template('league_dashboard.html', league=league,
                           tournaments=tournaments, player_count=player_count,
                           sponsorships=sponsorships,
                           invitable_bars=invitable_bars)
```

- [ ] **Step 6: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k invite -v`
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
git add routes/leagues.py templates/league_dashboard.html tests/test_sponsor_routes.py
git commit -m "leagues: invite existing bar to sponsor a league"
```

---

## Task 15: Bar dashboard view

**Files:**
- Create: `routes/bars.py`
- Create: `templates/bar_dashboard.html`
- Modify: `routes/__init__.py`
- Modify: `templates/base.html` (nav link)
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing test**

Append to `tests/test_sponsor_routes.py`:

```python
from models import BarMembership


def test_bar_dashboard_requires_membership(app):
    with app.app_context():
        op = _create_user('bd_op', is_admin=True)
        bar = Bar(name='Cactus', created_by_id=op.id, created_at=datetime.utcnow())
        outsider = _create_user('bd_out')
        db.session.add(bar)
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'bd_out')
    resp = client.get(f'/bar/{bid}')
    assert resp.status_code == 403


def test_bar_dashboard_renders_for_member(app):
    with app.app_context():
        creator = _create_user('bd_creator', is_admin=True)
        bar = Bar(name='CactusZZZ', created_by_id=creator.id,
                  created_at=datetime.utcnow())
        member = _create_user('bd_member')
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=member.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'bd_member')
    resp = client.get(f'/bar/{bid}')
    assert resp.status_code == 200
    assert b'CactusZZZ' in resp.data
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k bar_dashboard -v`
Expected: 404s — blueprint not registered.

- [ ] **Step 3: Create `routes/bars.py`**

```python
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from models import Bar, BarMembership, LeagueSponsorship, Tournament

bp = Blueprint('bars', __name__)


@bp.route('/bar/<int:bid>')
@login_required
def bar_dashboard(bid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage(current_user):
        abort(403)
    membership = BarMembership.query.filter_by(
        bar_id=bid, user_id=current_user.id
    ).first()
    is_primary = bool(membership and membership.is_primary) or current_user.is_admin
    sponsorships = LeagueSponsorship.query.filter_by(bar_id=bid).all()
    staff = BarMembership.query.filter_by(bar_id=bid).all()
    tournaments = Tournament.query.filter_by(bar_id=bid).order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()
    return render_template('bar_dashboard.html', bar=bar,
                           is_primary=is_primary, sponsorships=sponsorships,
                           staff=staff, tournaments=tournaments)
```

- [ ] **Step 4: Register the blueprint**

In `routes/__init__.py`, add the import and registration following the existing pattern. (View the file to find the registration list and add `from routes.bars import bp as bars_bp` plus `app.register_blueprint(bars_bp)`.)

- [ ] **Step 5: Create `templates/bar_dashboard.html`**

```html
{% extends 'base.html' %}
{% block title %}{{ bar.name }} — TourneyTracker{% endblock %}
{% block content %}
<header class="page-hero">
  <div>
    <div class="page-hero__mark">BAR · {{ current_user.username }}</div>
    <h1 class="page-hero__title">{{ bar.name }}</h1>
    {% if bar.address %}<p class="page-hero__sub">{{ bar.address }}</p>{% endif %}
  </div>
</header>

<div class="admin-grid">
  <section class="admin-block">
    <div class="section-head"><h2 class="section-head__title">Leagues sponsored</h2></div>
    {% if sponsorships %}
      <ul class="sponsors-list">
        {% for ls in sponsorships %}
          <li>{{ ls.league.name }}</li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="muted">Not sponsoring any league yet.</p>
    {% endif %}
  </section>

  {% if is_primary %}
    <section class="admin-block">
      <div class="section-head"><h2 class="section-head__title">Bar staff</h2></div>
      <ul class="sponsors-list">
        {% for m in staff %}
          <li>
            {{ m.user.username }}
            {% if m.is_primary %}<span class="badge">primary</span>{% endif %}
            {% if not m.is_primary %}
              <form method="post" action="{{ url_for('bars.remove_staff', bid=bar.id, mid=m.id) }}" style="display:inline">
                <button class="btn btn-link btn-danger">Remove</button>
              </form>
            {% endif %}
          </li>
        {% endfor %}
      </ul>
      <form method="post" action="{{ url_for('bars.invite_staff', bid=bar.id) }}" class="form-stack form-stack--inline">
        <input type="text" name="username" class="form-control" placeholder="Staff username" required>
        <input type="password" name="password" class="form-control" placeholder="Password (6+ chars)" minlength="6" required>
        <button class="btn btn-primary">Invite staff</button>
      </form>
    </section>
  {% endif %}

  <section class="admin-block">
    <div class="section-head"><h2 class="section-head__title">Recreational tournaments</h2></div>
    {% if tournaments %}
      <ul class="sponsors-list">
        {% for t in tournaments %}
          <li><a href="{{ url_for('tournaments.tournament', tid=t.id) }}">{{ t.name }}</a></li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No bar tournaments yet.</p>
    {% endif %}
    <form method="post" action="{{ url_for('bars.new_bar_tournament', bid=bar.id) }}" class="form-stack form-stack--inline">
      <input type="text" name="name" class="form-control" placeholder="Tournament name" required>
      <button class="btn btn-primary">Create tournament</button>
    </form>
  </section>
</div>
{% endblock %}
```

(Routes referenced from this template — `bars.invite_staff`, `bars.remove_staff`, `bars.new_bar_tournament` — are added in Tasks 16 and 17.)

- [ ] **Step 6: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k bar_dashboard -v`
Expected: 2 PASS. (The Jinja `url_for` calls reference routes added in later tasks; the test queries fail-fast errors are dampened by `BuildError`, so ensure those routes are at least stubbed or guard the form rendering with `{% if False %}` until Task 16. Cleanest: add stub routes returning 404 in `routes/bars.py` now.)

Add the stubs in `routes/bars.py`:

```python
@bp.route('/bar/<int:bid>/staff/invite', methods=['POST'])
@login_required
def invite_staff(bid):
    abort(404)


@bp.route('/bar/<int:bid>/staff/<int:mid>/remove', methods=['POST'])
@login_required
def remove_staff(bid, mid):
    abort(404)


@bp.route('/bar/<int:bid>/tournament/new', methods=['POST'])
@login_required
def new_bar_tournament(bid):
    abort(404)
```

These get real implementations in the next tasks.

- [ ] **Step 7: Add nav link**

In `templates/base.html`, alongside the existing nav links, add (inside the authenticated section):

```html
{% if current_user.is_authenticated and current_user.bar_memberships %}
  {% set m = current_user.bar_memberships|first %}
  <a href="{{ url_for('bars.bar_dashboard', bid=m.bar_id) }}">My Bar</a>
{% endif %}
```

This requires a backref. In `models.py`, update the `BarMembership` declaration to add `backref='bar_memberships'` on the `user` relationship:

```python
    user = db.relationship('Admin', foreign_keys=[user_id], backref='bar_memberships')
```

- [ ] **Step 8: Run the suite**

Run: `pytest -v`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add routes/bars.py routes/__init__.py templates/bar_dashboard.html templates/base.html models.py tests/test_sponsor_routes.py
git commit -m "bars: add bar dashboard with sponsorships, staff, and tournaments sections"
```

---

## Task 16: Bar staff invite & remove

**Files:**
- Modify: `routes/bars.py`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
def test_primary_invites_staff(app):
    with app.app_context():
        primary = _create_user('inv_primary')
        bar = Bar(name='InvBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'inv_primary')
    resp = client.post(f'/bar/{bid}/staff/invite', data={
        'username': 'newstaff', 'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='newstaff').first()
        assert u is not None
        assert u.is_admin is False
        m = BarMembership.query.filter_by(user_id=u.id, bar_id=bid).first()
        assert m is not None
        assert m.is_primary is False


def test_staff_cannot_invite_staff(app):
    with app.app_context():
        primary = _create_user('np_primary')
        staff = _create_user('np_staff')
        bar = Bar(name='NPBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.add(BarMembership(user_id=staff.id, bar_id=bar.id,
                                     is_primary=False))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'np_staff')
    resp = client.post(f'/bar/{bid}/staff/invite', data={
        'username': 'denied', 'password': 'secret123',
    })
    assert resp.status_code == 403


def test_remove_staff(app):
    with app.app_context():
        primary = _create_user('rm_primary')
        staff = _create_user('rm_staff')
        bar = Bar(name='RMBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        m = BarMembership(user_id=staff.id, bar_id=bar.id, is_primary=False)
        db.session.add(m)
        db.session.commit()
        bid, mid = bar.id, m.id
    client = app.test_client()
    _login(client, 'rm_primary')
    resp = client.post(f'/bar/{bid}/staff/{mid}/remove')
    assert resp.status_code == 302
    with app.app_context():
        assert BarMembership.query.get(mid) is None


def test_cannot_remove_primary_membership(app):
    with app.app_context():
        primary = _create_user('rmp_primary')
        bar = Bar(name='RMPBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        m = BarMembership(user_id=primary.id, bar_id=bar.id, is_primary=True)
        db.session.add(m)
        db.session.commit()
        bid, mid = bar.id, m.id
    client = app.test_client()
    _login(client, 'rmp_primary')
    resp = client.post(f'/bar/{bid}/staff/{mid}/remove', follow_redirects=False)
    # Should redirect with an error flash; primary membership not deleted.
    assert resp.status_code == 302
    with app.app_context():
        assert BarMembership.query.get(mid) is not None
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k staff -v`
Expected: 404s — stub routes from Task 15 still return abort(404).

- [ ] **Step 3: Implement the routes**

In `routes/bars.py`, replace the stubs with real implementations:

```python
from flask import request, redirect, url_for, flash
from app import db
from models import Admin


@bp.route('/bar/<int:bid>/staff/invite', methods=['POST'])
@login_required
def invite_staff(bid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage_staff(current_user):
        abort(403)
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or len(password) < 6:
        flash('Username and a 6+ character password required.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    u = Admin(username=username, is_admin=False, is_league_operator=False)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    db.session.add(BarMembership(user_id=u.id, bar_id=bid, is_primary=False))
    db.session.commit()
    flash(f'{username} added as bar staff.', 'success')
    return redirect(url_for('bars.bar_dashboard', bid=bid))


@bp.route('/bar/<int:bid>/staff/<int:mid>/remove', methods=['POST'])
@login_required
def remove_staff(bid, mid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage_staff(current_user):
        abort(403)
    m = BarMembership.query.get_or_404(mid)
    if m.bar_id != bid:
        abort(404)
    if m.is_primary:
        flash('Cannot remove the primary membership. Transfer primary first.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    db.session.delete(m)
    db.session.commit()
    flash('Staff removed.', 'info')
    return redirect(url_for('bars.bar_dashboard', bid=bid))
```

(The `new_bar_tournament` stub remains in place; it's fixed in Task 17.)

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k staff -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/bars.py tests/test_sponsor_routes.py
git commit -m "bars: invite and remove bar staff (primary only)"
```

---

## Task 17: Bar recreational tournament creation

**Files:**
- Modify: `routes/bars.py`
- Modify: `routes/tournaments.py` (validate league_id+bar_id mutual exclusion at create/edit time)
- Test: `tests/test_sponsor_routes.py`, `tests/test_bar_tournaments.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
def test_bar_member_creates_tournament(app):
    with app.app_context():
        primary = _create_user('bt_primary')
        bar = Bar(name='BTBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'bt_primary')
    resp = client.post(f'/bar/{bid}/tournament/new', data={'name': 'Friday Night'})
    assert resp.status_code == 302
    with app.app_context():
        from models import Tournament
        t = Tournament.query.filter_by(name='Friday Night').first()
        assert t is not None
        assert t.bar_id == bid
        assert t.league_id is None


def test_outsider_cannot_create_bar_tournament(app):
    with app.app_context():
        primary = _create_user('out_primary')
        outsider = _create_user('out_outsider')
        bar = Bar(name='OutBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'out_outsider')
    resp = client.post(f'/bar/{bid}/tournament/new', data={'name': 'Sneaky'})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k bar_member_creates -v`
Expected: 404 (stub). The other test passes for the wrong reason; we'll let real implementation pin both.

- [ ] **Step 3: Implement the route**

In `routes/bars.py`, replace the `new_bar_tournament` stub with:

```python
@bp.route('/bar/<int:bid>/tournament/new', methods=['POST'])
@login_required
def new_bar_tournament(bid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage(current_user):
        abort(403)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Tournament name required.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    t = Tournament(
        name=name, bar_id=bid, owner_id=current_user.id,
        buyin=10, table_fee=1.0, format='bestof', race_to=1,
        bracket_type='single', lb_format='bestof', lb_race_to=1,
        seeding='random',
    )
    db.session.add(t)
    db.session.commit()
    return redirect(url_for('tournaments.tournament', tid=t.id))
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k bar_member -v -k tournament`
Expected: 2 PASS.

- [ ] **Step 5: Add the league/bar mutual-exclusion guard**

This is the spec's "creating a tournament with both `league_id` and `bar_id` set → 400" rule. Today the only way `league_id` and `bar_id` both end up set is via direct DB manipulation, but we add a defensive validation in `Tournament.__init__` so any future route (or admin form) that does it gets caught.

In `models.py`, add to the `Tournament` class:

```python
    @db.validates('league_id', 'bar_id')
    def _validate_mutual_exclusion(self, key, value):
        # Lazy: at validate-time some attrs may not exist yet.
        other_key = 'bar_id' if key == 'league_id' else 'league_id'
        other = getattr(self, other_key, None)
        if value is not None and other is not None:
            raise ValueError(
                'A tournament belongs either to a league or to a bar, not both.'
            )
        return value
```

- [ ] **Step 6: Add a model-level test for the mutual-exclusion guard**

Append to `tests/test_bar_tournaments.py`:

```python
import pytest


def test_cannot_set_both_league_and_bar(app):
    with app.app_context():
        owner = _admin('mx', is_admin=True)
        bar = _bar(owner)
        league = _league(owner)
        with pytest.raises(ValueError):
            t = Tournament(name='Bad', league_id=league.id, bar_id=bar.id)
            db.session.add(t)
            db.session.flush()
```

- [ ] **Step 7: Run all bar/tournament tests**

Run: `pytest tests/test_bar_tournaments.py tests/test_sponsor_routes.py -v`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add routes/bars.py models.py tests/test_sponsor_routes.py tests/test_bar_tournaments.py
git commit -m "bars: create recreational tournament; reject league+bar mutual"
```

---

## Task 18: Login redirect priority

**Files:**
- Modify: `routes/auth.py`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `tests/test_sponsor_routes.py`:

```python
def test_bar_only_user_redirects_to_bar(app):
    with app.app_context():
        creator = _create_user('lr_creator', is_admin=True)
        member = _create_user('lr_member')
        bar = Bar(name='LRBar', created_by_id=creator.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=member.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    resp = client.post('/login', data={'username': 'lr_member', 'password': 'secret123'},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/bar/{bid}')


def test_operator_redirects_to_leagues_list(app):
    with app.app_context():
        _create_user('lr_op', is_league_operator=True)
    client = app.test_client()
    resp = client.post('/login', data={'username': 'lr_op', 'password': 'secret123'},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/leagues')
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k redirect -v`
Expected: bar-member test fails — they're sent to `/leagues` today.

- [ ] **Step 3: Update `routes/auth.py`**

Replace the post-login redirect logic in `login()`:

```python
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_post_login_target(current_user))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin, remember=request.form.get('remember') == 'on')
            return redirect(request.args.get('next') or _post_login_target(admin))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


def _post_login_target(user):
    """Return the URL to send `user` to after login.

    Priority:
      1. League-management context (admin/operator/delegate) → /leagues
      2. Otherwise, any bar membership → first bar's dashboard
      3. Otherwise → public landing
    """
    from models import get_user_leagues, BarMembership
    if user.is_admin or user.is_league_operator or get_user_leagues(user):
        return url_for('leagues.league_list')
    bm = BarMembership.query.filter_by(user_id=user.id).first()
    if bm:
        return url_for('bars.bar_dashboard', bid=bm.bar_id)
    return url_for('tournaments.index')
```

- [ ] **Step 4: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k redirect -v`
Expected: 2 PASS.

Run: `pytest -v`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add routes/auth.py tests/test_sponsor_routes.py
git commit -m "auth: post-login redirect priority leagues > bar > public"
```

---

## Task 19: Admin Bars panel

**Files:**
- Modify: `routes/admin.py`
- Modify: `templates/admin.html`
- Test: `tests/test_sponsor_routes.py` (extend)

- [ ] **Step 1: Failing test**

Append to `tests/test_sponsor_routes.py`:

```python
def test_admin_panel_lists_bars(app):
    with app.app_context():
        admin = _create_user('ab_admin', is_admin=True)
        bar = Bar(name='ABBar', created_by_id=admin.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.commit()
    client = app.test_client()
    _login(client, 'ab_admin')
    resp = client.get('/admin')
    assert resp.status_code == 200
    assert b'ABBar' in resp.data
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_sponsor_routes.py -k admin_panel_lists_bars -v`
Expected: FAIL — `ABBar` not in response.

- [ ] **Step 3: Pass `bars` to the template**

In `routes/admin.py:20-37`, update `admin_panel`:

```python
@bp.route('/admin')
@admin_required
def admin_panel():
    from models import Bar
    admins = Admin.query.order_by(Admin.username).all()
    stats = {
        'tournaments': Tournament.query.count(),
        'players': PlayerProfile.query.count(),
        'matches': Match.query.count(),
        'complete': Tournament.query.filter_by(status='complete').count(),
        'open': Tournament.query.filter_by(status='open').count(),
        'in_progress': Tournament.query.filter_by(status='bracket').count(),
        'leagues': League.query.count(),
        'bars': Bar.query.count(),
    }
    tournaments = Tournament.query.order_by(Tournament.id.desc()).all()
    players = PlayerProfile.query.order_by(PlayerProfile.first_name, PlayerProfile.last_name).all()
    leagues = League.query.order_by(League.name).all()
    bars = Bar.query.order_by(Bar.name).all()
    return render_template('admin.html', admins=admins, stats=stats,
                           tournaments=tournaments, players=players,
                           leagues=leagues, bars=bars)
```

- [ ] **Step 4: Render the section**

In `templates/admin.html`, find the existing leagues section and append a similar Bars section:

```html
<section class="admin-block">
  <div class="section-head">
    <h2 class="section-head__title">Bars</h2>
    <span class="section-head__count">{{ bars|length }}</span>
  </div>
  {% if bars %}
    <ul class="sponsors-list">
      {% for b in bars %}
        <li>
          <a href="{{ url_for('bars.bar_dashboard', bid=b.id) }}">{{ b.name }}</a>
          {% set primary = b.memberships|selectattr('is_primary')|first %}
          {% if primary %}<span class="muted">{{ primary.user.username }}</span>{% endif %}
          <span class="muted">· {{ b.sponsorships|length }} league(s)</span>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">No bars yet.</p>
  {% endif %}
</section>
```

- [ ] **Step 5: Run and confirm pass**

Run: `pytest tests/test_sponsor_routes.py -k admin_panel_lists_bars -v`
Expected: PASS.

Run: `pytest -v`
Expected: full suite green.

- [ ] **Step 6: Commit**

```bash
git add routes/admin.py templates/admin.html tests/test_sponsor_routes.py
git commit -m "admin: list bars on the admin panel"
```

---

## Task 20: Final integration sweep

**Files:**
- Run the app, sanity-check the new flows in a browser.
- Run the full test suite.

- [ ] **Step 1: Run the full suite**

Run: `pytest -v`
Expected: all tests green.

- [ ] **Step 2: Boot the app**

```bash
source .venv/bin/activate
FLASK_DEBUG=1 python app.py
```

- [ ] **Step 3: Manual smoke test**

In a browser at `http://localhost:5050`:

1. Log in as `admin / admin123`.
2. From the admin panel, create a user with both flags off.
3. Confirm the Bars section is empty.
4. Create a league (default flow).
5. From the league dashboard, onboard a new bar named "Cactus" with a primary sponsor "cactus_owner / secret123".
6. Log out, log in as `cactus_owner` — should redirect to the Cactus bar dashboard.
7. From the bar dashboard, invite a staff user and create a recreational tournament.
8. Verify the tournament shows on the bar dashboard and the bar shows on the admin panel.

- [ ] **Step 4: Commit any docs you decide to add**

```bash
git status
# If nothing uncommitted, you're done.
```

---

## Self-review checklist

After implementing all tasks, verify the spec is fully covered:

- [x] Rename `Admin` → `User` (Task 11)
- [x] `is_admin` and `is_league_operator` columns + role backfill (Tasks 2, 11)
- [x] `PlayerProfile.user_id` reserved column (Task 7)
- [x] `Bar`, `BarMembership`, `LeagueSponsorship` tables (Tasks 4, 5, 6)
- [x] `Tournament.bar_id` column (Task 8)
- [x] `auth_helpers.py` with `can_create_league`, `can_create_bar`, `can_promote_user`, `can_act_as_sponsor` (Tasks 3, 9)
- [x] `Bar.can_manage`, `Bar.can_manage_staff` (Task 8)
- [x] Extended `Tournament.can_manage` with bar path (Task 8)
- [x] Admin panel: role checkboxes (Task 11) and Bars list (Task 19)
- [x] League dashboard: Sponsors panel + invite/onboard/remove (Tasks 12, 13, 14)
- [x] `routes/bars.py` blueprint with bar dashboard (Task 15), staff invite/remove (Task 16), recreational tournament creation (Task 17)
- [x] Both-IDs validation (Task 17 step 5)
- [x] Login redirect priority (Task 18)
- [x] Migration test (Task 11)
- [x] All five test files mentioned in the spec exist with the named tests
