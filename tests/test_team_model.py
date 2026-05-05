from datetime import datetime
from app import db
from models import User, Bar, League, LeagueSponsorship, Team
from sqlalchemy.exc import IntegrityError
from models import PlayerProfile, TeamMembership


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


def _team_with_player(app, profile_kwargs=None):
    u = _user('tu_helper', is_admin=True)
    bar, league = _bar_and_league(u)
    team = Team(name='Cactus A', bar_id=bar.id, league_id=league.id,
                created_by_id=u.id, created_at=datetime.utcnow())
    db.session.add(team)
    db.session.flush()
    profile = PlayerProfile(first_name='John', last_name='Doe',
                            league_id=league.id, **(profile_kwargs or {}))
    db.session.add(profile)
    db.session.commit()
    return u, bar, league, team, profile


def test_team_membership_persists(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        m = TeamMembership(team_id=team.id, profile_id=profile.id,
                           is_captain=True)
        db.session.add(m)
        db.session.commit()
        fetched = TeamMembership.query.first()
        assert fetched.is_captain is True
        assert fetched.is_co_captain is False
        assert fetched.is_scorekeeper is False
        assert fetched.is_sub is False


def test_team_member_unique(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_captain_per_team(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        db.session.add(p2)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=p2.id, is_captain=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_co_captain_per_team(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        db.session.add(p2)
        db.session.flush()
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id, is_co_captain=True))
        db.session.commit()
        db.session.add(TeamMembership(team_id=team.id, profile_id=p2.id, is_co_captain=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_many_scorekeepers_allowed(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        p2 = PlayerProfile(first_name='Jane', last_name='Doe', league_id=league.id)
        p3 = PlayerProfile(first_name='Joe', last_name='Schmoe', league_id=league.id)
        db.session.add_all([p2, p3])
        db.session.flush()
        for p in (profile, p2, p3):
            db.session.add(TeamMembership(team_id=team.id, profile_id=p.id, is_scorekeeper=True))
        db.session.commit()
        assert TeamMembership.query.filter_by(team_id=team.id, is_scorekeeper=True).count() == 3


from auth_helpers import can_create_team


def test_can_create_team_requires_sponsorship(app):
    with app.app_context():
        admin = _user('cct_admin', is_admin=True)
        bar = Bar(name='B', created_by_id=admin.id, created_at=datetime.utcnow())
        league = League(name='L', owner_id=admin.id)
        db.session.add_all([bar, league])
        db.session.commit()
        # No LeagueSponsorship row → cannot create even as admin? Yes, because creation
        # is gated on sponsorship existing for non-admins. Admins always pass.
        assert can_create_team(admin, bar, league) is True

        sponsor = _user('cct_sponsor')
        from models import BarMembership
        db.session.add(BarMembership(user_id=sponsor.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # Bar member but no sponsorship → False.
        assert can_create_team(sponsor, bar, league) is False

        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=admin.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        assert can_create_team(sponsor, bar, league) is True


def test_team_can_manage_roster(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        admin = u  # already admin
        assert team.can_manage_roster(admin) is True

        outsider = _user('tcr_outsider')
        assert team.can_manage_roster(outsider) is False

        from models import BarMembership
        staff = _user('tcr_staff')
        db.session.add(BarMembership(user_id=staff.id, bar_id=bar.id, is_primary=False))
        db.session.commit()
        assert team.can_manage_roster(staff) is True


def test_team_can_assign_scorekeeper(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        admin = u
        assert team.can_assign_scorekeeper(admin) is True

        # Captain assigned via team membership; profile.user_id linked.
        captain_user = _user('cap')
        profile.user_id = captain_user.id
        m = TeamMembership(team_id=team.id, profile_id=profile.id, is_captain=True)
        db.session.add(m)
        db.session.commit()
        assert team.can_assign_scorekeeper(captain_user) is True

        outsider = _user('cap_outsider')
        assert team.can_assign_scorekeeper(outsider) is False


def test_team_is_member(app):
    with app.app_context():
        u, bar, league, team, profile = _team_with_player(app)
        member_user = _user('member')
        profile.user_id = member_user.id
        db.session.add(TeamMembership(team_id=team.id, profile_id=profile.id))
        db.session.commit()
        assert team.is_member(member_user) is True

        non_member = _user('non_member')
        assert team.is_member(non_member) is False
