from datetime import datetime
from app import db
from models import Admin, Bar, BarMembership, League, Tournament


def _admin(username, **flags):
    u = Admin(username=username, **flags)
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
