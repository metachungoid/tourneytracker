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
    ]:
        try:
            db.session.execute(db.text(col_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()
    create_default_admin()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=5050)
