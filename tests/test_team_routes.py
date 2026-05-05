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
