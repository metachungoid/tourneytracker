from datetime import datetime
from app import db
from models import Admin, Bar


def _make_admin(username='admin1'):
    u = Admin(username=username, role='admin', is_admin=True)
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
