from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app import db
from models import Admin, Bar, League, LeagueSponsorship


def _seed(app):
    admin = Admin(username='ls_admin', is_admin=True)
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


from auth_helpers import can_act_as_sponsor
from models import BarMembership


def _seed_full(app):
    admin, league, bar = _seed(app)
    sponsor = Admin(username='spons', is_admin=False)
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
        outsider = Admin(username='outsider')
        outsider.set_password('x' * 6)
        db.session.add(outsider)
        db.session.commit()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        assert can_act_as_sponsor(outsider, league, bar) is False
