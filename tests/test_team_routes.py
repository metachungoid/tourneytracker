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


def test_second_captain_rejected_with_flash(app):
    """The partial unique index protects the DB; the route must catch
    the IntegrityError and surface a flash + redirect, not a 500."""
    with app.app_context():
        creator, sponsor, bar, league, team, profile = _team_with_profile(app)
        # First captain
        u1 = _create_user('cap1_user')
        profile.user_id = u1.id
        cap1 = TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True)
        # Second profile, no current captain flag
        p2 = PlayerProfile(first_name='Second', last_name='Cap', league_id=league.id)
        u2 = _create_user('cap2_user')
        p2.user_id = u2.id
        db.session.add_all([cap1, p2])
        db.session.flush()
        m2 = TeamMembership(team_id=team.id, profile_id=p2.id)
        db.session.add(m2)
        db.session.commit()
        tid, mid = team.id, m2.id
    client = app.test_client()
    _login(client, 'tr_sponsor')
    resp = client.post(f'/team/{tid}/roster/{mid}/role', data={'role': 'captain'},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        m = TeamMembership.query.get(mid)
        assert m.is_captain is False, 'second captain must not be set'
        # Original captain still in place
        first = TeamMembership.query.filter_by(team_id=tid, is_captain=True).all()
        assert len(first) == 1
