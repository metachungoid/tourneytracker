from app import db
from models import Admin


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
