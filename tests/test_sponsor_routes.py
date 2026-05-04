from app import db
from models import Admin


def _create_user(username, password='secret123', **flags):
    u = Admin(username=username, **flags)
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


def test_admin_creates_user_with_both_flags(app):
    with app.app_context():
        _create_user('boss', is_admin=True)
    client = app.test_client()
    _login(client, 'boss')
    resp = client.post('/admin/add_user', data={
        'username': 'dual', 'password': 'secret123',
        'is_admin': '1', 'is_league_operator': '1',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='dual').first()
        assert u.is_admin is True
        assert u.is_league_operator is True


def test_admin_creates_user_with_neither_flag(app):
    with app.app_context():
        _create_user('boss2', is_admin=True)
    client = app.test_client()
    _login(client, 'boss2')
    resp = client.post('/admin/add_user', data={
        'username': 'plain1', 'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='plain1').first()
        assert u.is_admin is False
        assert u.is_league_operator is False


from datetime import datetime
from models import Bar, League, LeagueSponsorship


def _seed_league_with_sponsor(app):
    op = _create_user('lop', is_league_operator=True)
    league = League(name='LX', owner_id=op.id)
    bar = Bar(name='Cactus', created_by_id=op.id, created_at=datetime.utcnow())
    db.session.add_all([league, bar])
    db.session.flush()
    ls = LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                           invited_by_id=op.id, invited_at=datetime.utcnow())
    db.session.add(ls)
    db.session.commit()
    return op, league, bar, ls


def test_dashboard_lists_sponsor(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        lid = league.id
    client = app.test_client()
    _login(client, 'lop')
    resp = client.get(f'/league/{lid}')
    assert resp.status_code == 200
    assert b'Cactus' in resp.data


def test_remove_sponsor(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        lid, sid = league.id, ls.id
    client = app.test_client()
    _login(client, 'lop')
    resp = client.post(f'/league/{lid}/sponsor/{sid}/remove')
    assert resp.status_code == 302
    with app.app_context():
        assert LeagueSponsorship.query.get(sid) is None
        # Bar still exists.
        assert Bar.query.first() is not None


def test_remove_sponsor_requires_league_management(app):
    with app.app_context():
        op, league, bar, ls = _seed_league_with_sponsor(app)
        outsider = _create_user('outsider')
        lid, sid = league.id, ls.id
    client = app.test_client()
    _login(client, 'outsider')
    resp = client.post(f'/league/{lid}/sponsor/{sid}/remove')
    assert resp.status_code == 403
    with app.app_context():
        assert LeagueSponsorship.query.get(sid) is not None


from models import BarMembership


def test_onboard_new_bar_creates_full_chain(app):
    with app.app_context():
        op = _create_user('onb_op', is_league_operator=True)
        league = League(name='LO', owner_id=op.id)
        db.session.add(league)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'onb_op')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'Cactus',
        'sponsor_username': 'cactus_owner',
        'sponsor_password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        bar = Bar.query.filter_by(name='Cactus').first()
        assert bar is not None
        u = Admin.query.filter_by(username='cactus_owner').first()
        assert u is not None
        assert u.is_admin is False
        assert u.is_league_operator is False
        m = BarMembership.query.filter_by(user_id=u.id, bar_id=bar.id).first()
        assert m is not None
        assert m.is_primary is True
        ls = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bar.id).first()
        assert ls is not None


def test_onboard_rejects_duplicate_username(app):
    with app.app_context():
        op = _create_user('dup_op', is_league_operator=True)
        league = League(name='LD', owner_id=op.id)
        db.session.add(league)
        # An existing user with this username already exists.
        existing = Admin(username='taken')
        existing.set_password('x' * 6)
        db.session.add(existing)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'dup_op')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'Other',
        'sponsor_username': 'taken',
        'sponsor_password': 'secret123',
    }, follow_redirects=True)
    # Redirect back to dashboard with an error flash; no bar created.
    with app.app_context():
        assert Bar.query.filter_by(name='Other').first() is None


def test_onboard_requires_league_management(app):
    with app.app_context():
        op = _create_user('o3_op', is_league_operator=True)
        outsider = _create_user('o3_out')
        league = League(name='L3', owner_id=op.id)
        db.session.add(league)
        db.session.commit()
        lid = league.id
    client = app.test_client()
    _login(client, 'o3_out')
    resp = client.post(f'/league/{lid}/sponsor/onboard', data={
        'bar_name': 'X', 'sponsor_username': 'x', 'sponsor_password': 'secret123',
    })
    assert resp.status_code == 403


def test_invite_existing_bar(app):
    with app.app_context():
        op = _create_user('inv_op', is_league_operator=True)
        league = League(name='LI', owner_id=op.id)
        bar = Bar(name='Existing', created_by_id=op.id,
                  created_at=datetime.utcnow())
        db.session.add_all([league, bar])
        db.session.commit()
        lid, bid = league.id, bar.id
    client = app.test_client()
    _login(client, 'inv_op')
    resp = client.post(f'/league/{lid}/sponsor/invite', data={'bar_id': bid})
    assert resp.status_code == 302
    with app.app_context():
        ls = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bid).first()
        assert ls is not None


def test_invite_duplicate_rejected(app):
    with app.app_context():
        op = _create_user('inv2_op', is_league_operator=True)
        league = League(name='LI2', owner_id=op.id)
        bar = Bar(name='Existing2', created_by_id=op.id,
                  created_at=datetime.utcnow())
        db.session.add_all([league, bar])
        db.session.flush()
        db.session.add(LeagueSponsorship(league_id=league.id, bar_id=bar.id,
                                         invited_by_id=op.id,
                                         invited_at=datetime.utcnow()))
        db.session.commit()
        lid, bid = league.id, bar.id
    client = app.test_client()
    _login(client, 'inv2_op')
    resp = client.post(f'/league/{lid}/sponsor/invite', data={'bar_id': bid},
                       follow_redirects=False)
    # Should redirect with a flash, not crash. Only one row exists.
    assert resp.status_code == 302
    with app.app_context():
        rows = LeagueSponsorship.query.filter_by(league_id=lid, bar_id=bid).all()
        assert len(rows) == 1


def test_bar_dashboard_requires_membership(app):
    with app.app_context():
        op = _create_user('bd_op', is_admin=True)
        bar = Bar(name='Cactus', created_by_id=op.id, created_at=datetime.utcnow())
        outsider = _create_user('bd_out')
        db.session.add(bar)
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'bd_out')
    resp = client.get(f'/bar/{bid}')
    assert resp.status_code == 403


def test_bar_dashboard_renders_for_member(app):
    with app.app_context():
        creator = _create_user('bd_creator', is_admin=True)
        bar = Bar(name='CactusZZZ', created_by_id=creator.id,
                  created_at=datetime.utcnow())
        member = _create_user('bd_member')
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=member.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'bd_member')
    resp = client.get(f'/bar/{bid}')
    assert resp.status_code == 200
    assert b'CactusZZZ' in resp.data


def test_primary_invites_staff(app):
    with app.app_context():
        primary = _create_user('inv_primary')
        bar = Bar(name='InvBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'inv_primary')
    resp = client.post(f'/bar/{bid}/staff/invite', data={
        'username': 'newstaff', 'password': 'secret123',
    })
    assert resp.status_code == 302
    with app.app_context():
        u = Admin.query.filter_by(username='newstaff').first()
        assert u is not None
        assert u.is_admin is False
        m = BarMembership.query.filter_by(user_id=u.id, bar_id=bid).first()
        assert m is not None
        assert m.is_primary is False


def test_staff_cannot_invite_staff(app):
    with app.app_context():
        primary = _create_user('np_primary')
        staff = _create_user('np_staff')
        bar = Bar(name='NPBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        db.session.add(BarMembership(user_id=staff.id, bar_id=bar.id,
                                     is_primary=False))
        db.session.commit()
        bid = bar.id
    client = app.test_client()
    _login(client, 'np_staff')
    resp = client.post(f'/bar/{bid}/staff/invite', data={
        'username': 'denied', 'password': 'secret123',
    })
    assert resp.status_code == 403


def test_remove_staff(app):
    with app.app_context():
        primary = _create_user('rm_primary')
        staff = _create_user('rm_staff')
        bar = Bar(name='RMBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        db.session.add(BarMembership(user_id=primary.id, bar_id=bar.id,
                                     is_primary=True))
        m = BarMembership(user_id=staff.id, bar_id=bar.id, is_primary=False)
        db.session.add(m)
        db.session.commit()
        bid, mid = bar.id, m.id
    client = app.test_client()
    _login(client, 'rm_primary')
    resp = client.post(f'/bar/{bid}/staff/{mid}/remove')
    assert resp.status_code == 302
    with app.app_context():
        assert BarMembership.query.get(mid) is None


def test_cannot_remove_primary_membership(app):
    with app.app_context():
        primary = _create_user('rmp_primary')
        bar = Bar(name='RMPBar', created_by_id=primary.id,
                  created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.flush()
        m = BarMembership(user_id=primary.id, bar_id=bar.id, is_primary=True)
        db.session.add(m)
        db.session.commit()
        bid, mid = bar.id, m.id
    client = app.test_client()
    _login(client, 'rmp_primary')
    resp = client.post(f'/bar/{bid}/staff/{mid}/remove', follow_redirects=False)
    # Should redirect with an error flash; primary membership not deleted.
    assert resp.status_code == 302
    with app.app_context():
        assert BarMembership.query.get(mid) is not None
