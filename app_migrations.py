"""One-shot schema migrations runnable independently of Flask startup.

Used in production via `app.py`'s startup path AND directly by tests
that need to assert migration behavior.
"""
from sqlalchemy import inspect, text


def migrate_admin_to_user(engine):
    """Rename `admin` to `user`, backfill the boolean flags, drop `role`.

    Idempotent: safe to run when `user` already exists or when the
    boolean columns are already present.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    with engine.begin() as conn:
        # 1. Rename the table if needed.
        if 'admin' in tables and 'user' not in tables:
            conn.execute(text('ALTER TABLE admin RENAME TO user'))
            tables.discard('admin')
            tables.add('user')

        if 'user' not in tables:
            return  # fresh install — db.create_all will build it from the model

        # 2. Add the new columns if missing.
        cols = {c['name'] for c in inspect(engine).get_columns('user')}
        if 'is_admin' not in cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
        if 'is_league_operator' not in cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN is_league_operator BOOLEAN NOT NULL DEFAULT 0"))

        # 3. Backfill from `role` if it still exists.
        cols = {c['name'] for c in inspect(engine).get_columns('user')}
        if 'role' in cols:
            conn.execute(text("UPDATE user SET is_admin = 1 WHERE role = 'admin'"))
            conn.execute(text(
                "UPDATE user SET is_league_operator = 1 WHERE role = 'manager'"
            ))
            # 4. Drop the role column. SQLite ≥3.35 supports DROP COLUMN.
            conn.execute(text("ALTER TABLE user DROP COLUMN role"))
