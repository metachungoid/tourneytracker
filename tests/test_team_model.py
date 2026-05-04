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
