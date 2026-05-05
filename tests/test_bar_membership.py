from datetime import datetime
from app import db
from models import Admin, Bar
from sqlalchemy.exc import IntegrityError
from models import BarMembership


def _make_admin(username='admin1'):
    u = Admin(username=username, is_admin=True)
    u.set_password('x' * 6)
    db.session.add(u)
    db.session.commit()
    return u


def test_bar_creation_persists(app):
    with app.app_context():
        creator = _make_admin('creator')
        bar = Bar(name='Cactus', address='123 Main St', phone='555-1212',
                  created_by_id=creator.id, created_at=datetime.utcnow())
        db.session.add(bar)
        db.session.commit()
        fetched = Bar.query.filter_by(name='Cactus').first()
        assert fetched is not None
        assert fetched.address == '123 Main St'
        assert fetched.phone == '555-1212'
        assert fetched.created_by_id == creator.id
        assert fetched.created_at is not None


def test_bar_name_required(app):
    with app.app_context():
        from sqlalchemy.exc import IntegrityError
        bar = Bar(name=None, created_by_id=None)
        db.session.add(bar)
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def _make_bar(creator=None):
    if creator is None:
        creator = _make_admin('barmaker')
    bar = Bar(name='Cactus', created_by_id=creator.id, created_at=datetime.utcnow())
    db.session.add(bar)
    db.session.commit()
    return bar


def test_user_bar_unique(app):
    with app.app_context():
        u = _make_admin('u1')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # Second membership for same (user, bar) must fail.
        db.session.add(BarMembership(user_id=u.id, bar_id=bar.id, is_primary=False))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_only_one_primary_per_bar(app):
    with app.app_context():
        u1 = _make_admin('m1')
        u2 = _make_admin('m2')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u1.id, bar_id=bar.id, is_primary=True))
        db.session.commit()
        # A second is_primary=True for the same bar must fail.
        db.session.add(BarMembership(user_id=u2.id, bar_id=bar.id, is_primary=True))
        try:
            db.session.commit()
            assert False, 'expected IntegrityError'
        except IntegrityError:
            db.session.rollback()


def test_many_non_primary_allowed(app):
    with app.app_context():
        u1 = _make_admin('s1')
        u2 = _make_admin('s2')
        u3 = _make_admin('s3')
        bar = _make_bar()
        db.session.add(BarMembership(user_id=u1.id, bar_id=bar.id, is_primary=True))
        db.session.add(BarMembership(user_id=u2.id, bar_id=bar.id, is_primary=False))
        db.session.add(BarMembership(user_id=u3.id, bar_id=bar.id, is_primary=False))
        db.session.commit()
        assert BarMembership.query.filter_by(bar_id=bar.id).count() == 3
