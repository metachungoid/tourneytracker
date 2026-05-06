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
