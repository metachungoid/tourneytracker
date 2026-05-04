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
