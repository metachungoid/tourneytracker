import os
import sys
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# Ensure this module is registered as 'app' even when run as __main__,
# so that `from app import db` in models.py finds this module instead
# of triggering a second import of app.py.
sys.modules.setdefault('app', sys.modules[__name__])

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI', 'sqlite:///tourneytracker.db')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tourney-super-secret-2025')

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'

# Import models (registers them with db) and routes (registers blueprints)
from models import *  # noqa: E402, F401, F403
from routes import register_routes  # noqa: E402
register_routes(app)


@app.context_processor
def inject_league_context():
    from flask_login import current_user
    if current_user.is_authenticated:
        from models import get_user_leagues
        return {'user_leagues': get_user_leagues(current_user)}
    return {'user_leagues': []}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def create_default_admin():
    if not Admin.query.filter_by(username='admin').first():
        a = Admin(username='admin')
        a.set_password('admin123')
        db.session.add(a)
        db.session.commit()
        print('Default admin created  →  username: admin  /  password: admin123')


with app.app_context():
    db.create_all()
    # Migration: add new columns for double elimination support
    for col_sql in [
        "ALTER TABLE tournament ADD COLUMN bracket_type VARCHAR(10) DEFAULT 'single'",
        "ALTER TABLE tournament ADD COLUMN lb_format VARCHAR(20) DEFAULT 'bestof'",
        "ALTER TABLE tournament ADD COLUMN lb_race_to INTEGER DEFAULT 1",
        "ALTER TABLE admin ADD COLUMN role VARCHAR(20) DEFAULT 'admin'",
        "ALTER TABLE tournament ADD COLUMN owner_id INTEGER REFERENCES admin(id)",
        "ALTER TABLE player_profile ADD COLUMN first_name VARCHAR(50)",
        "ALTER TABLE player_profile ADD COLUMN last_name VARCHAR(50)",
        "CREATE TABLE IF NOT EXISTS league (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(100) NOT NULL, owner_id INTEGER NOT NULL REFERENCES admin(id))",
        "ALTER TABLE player_profile ADD COLUMN league_id INTEGER REFERENCES league(id)",
        "ALTER TABLE tournament ADD COLUMN league_id INTEGER REFERENCES league(id)",
        "ALTER TABLE manager_share ADD COLUMN league_id INTEGER REFERENCES league(id)",
    ]:
        try:
            db.session.execute(db.text(col_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Migrate legacy name → first_name + last_name
    from models import PlayerProfile, League, ManagerShare
    for p in PlayerProfile.query.filter(
        PlayerProfile.first_name.is_(None),
        PlayerProfile.name.isnot(None),
    ).all():
        parts = p.name.strip().split(None, 1)
        p.first_name = parts[0]
        p.last_name = parts[1] if len(parts) > 1 else ''
    db.session.commit()

    # Migrate existing data into leagues (one default league per manager/admin who owns tournaments)
    if League.query.count() == 0:
        owner_ids = {t.owner_id for t in Tournament.query.filter(
            Tournament.owner_id.isnot(None)
        ).all()}
        for a in Admin.query.filter_by(role='manager').all():
            owner_ids.add(a.id)
        if not owner_ids:
            admin_user = Admin.query.filter_by(role='admin').first()
            if admin_user:
                owner_ids.add(admin_user.id)
        for oid in owner_ids:
            owner = db.session.get(Admin, oid)
            league = League(name=f"{owner.username}'s League", owner_id=oid)
            db.session.add(league)
            db.session.flush()
            Tournament.query.filter_by(owner_id=oid).update({'league_id': league.id})
        first_league = League.query.first()
        if first_league:
            Tournament.query.filter(Tournament.league_id.is_(None)).update({'league_id': first_league.id})
            PlayerProfile.query.filter(PlayerProfile.league_id.is_(None)).update({'league_id': first_league.id})
        # Migrate ManagerShare: owner_id → league_id
        for share in ManagerShare.query.filter(ManagerShare.league_id.is_(None)).all():
            league = League.query.filter_by(owner_id=share.owner_id).first()
            if league:
                share.league_id = league.id
        db.session.commit()

    create_default_admin()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=5050)
