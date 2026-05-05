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
    tm = TeamMembership.query.filter_by(team_id=team.id).first()
    return team.id, tm.id


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
