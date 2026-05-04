from app import db
from models import Admin


def _create_user(username, password='secret123', **flags):
    u = Admin(username=username, role='admin' if flags.get('is_admin') else 'manager', **flags)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password='secret123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)


def test_plain_user_cannot_create_league(app):
    with app.app_context():
        _create_user('plain', is_admin=False, is_league_operator=False)
    client = app.test_client()
    _login(client, 'plain')
    resp = client.post('/league/new', data={'name': 'Forbidden'})
    assert resp.status_code == 403


def test_operator_can_create_league(app):
    with app.app_context():
        _create_user('op', is_league_operator=True)
    client = app.test_client()
    _login(client, 'op')
    resp = client.post('/league/new', data={'name': 'OK League'},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        from models import League
        assert League.query.filter_by(name='OK League').first() is not None


def test_admin_can_create_league(app):
    with app.app_context():
        _create_user('admin1', is_admin=True)
    client = app.test_client()
    _login(client, 'admin1')
    resp = client.post('/league/new', data={'name': 'Admin League'},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        from models import League
        assert League.query.filter_by(name='Admin League').first() is not None
