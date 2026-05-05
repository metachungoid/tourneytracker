from datetime import datetime
from app import db
from models import User, Bar, BarMembership, League, LeagueSponsorship, Team, PlayerProfile, TeamMembership


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
