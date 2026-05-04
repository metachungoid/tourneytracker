from app import db
from models import Admin
from auth_helpers import can_create_league, can_create_bar, can_promote_user


def test_admin_flag_grants_admin_capability(app):
    with app.app_context():
        u = Admin(username='boss', is_admin=True, is_league_operator=False)
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        assert u.is_admin is True
        assert u.is_league_operator is False


def test_operator_flag_persists(app):
    with app.app_context():
        u = Admin(username='op', is_admin=False, is_league_operator=True)
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        fetched = Admin.query.filter_by(username='op').first()
        assert fetched.is_admin is False
        assert fetched.is_league_operator is True


def test_neither_flag_is_default(app):
    with app.app_context():
        u = Admin(username='plain')
        u.set_password('x' * 6)
        db.session.add(u)
        db.session.commit()
        fetched = Admin.query.filter_by(username='plain').first()
        assert fetched.is_admin is False
        assert fetched.is_league_operator is False


def _make_user(is_admin=False, is_league_operator=False, username='u'):
    u = Admin(username=username, is_admin=is_admin, is_league_operator=is_league_operator)
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def test_can_create_league_admin(app):
    with app.app_context():
        u = _make_user(is_admin=True, username='a')
        assert can_create_league(u) is True


def test_can_create_league_operator(app):
    with app.app_context():
        u = _make_user(is_league_operator=True, username='op')
        assert can_create_league(u) is True


def test_can_create_league_neither_denied(app):
    with app.app_context():
        u = _make_user(username='plain2')
        assert can_create_league(u) is False


def test_can_create_league_anonymous(app):
    from flask_login import AnonymousUserMixin
    with app.app_context():
        assert can_create_league(AnonymousUserMixin()) is False


def test_can_create_bar_matches_create_league(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='ba')
        op = _make_user(is_league_operator=True, username='bo')
        plain = _make_user(username='bp')
        assert can_create_bar(admin) is True
        assert can_create_bar(op) is True
        assert can_create_bar(plain) is False


def test_can_promote_user_admin_only(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='pa')
        op = _make_user(is_league_operator=True, username='po')
        assert can_promote_user(admin) is True
        assert can_promote_user(op) is False


from models import PlayerProfile


def test_player_profile_user_id_optional(app):
    with app.app_context():
        admin = _make_user(is_admin=True, username='pp_admin')
        from models import League
        league = League(name='L', owner_id=admin.id)
        db.session.add(league)
        db.session.flush()
        # Without user_id
        p1 = PlayerProfile(first_name='Anon', last_name='', league_id=league.id)
        # With user_id linking back to a user
        p2 = PlayerProfile(first_name='Linked', last_name='', league_id=league.id,
                           user_id=admin.id)
        db.session.add_all([p1, p2])
        db.session.commit()
        assert PlayerProfile.query.filter_by(first_name='Anon').first().user_id is None
        assert PlayerProfile.query.filter_by(first_name='Linked').first().user_id == admin.id
