"""Verify the admin → user rename and role drop migration.

Strategy: start a fresh in-memory engine, build the OLD schema by hand,
populate it, then run the migration helper and assert the resulting
schema matches what the new model expects.
"""
import pytest
from sqlalchemy import create_engine, text, inspect


@pytest.fixture
def old_db():
    """An in-memory SQLite with the pre-migration schema."""
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(80) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'admin'
            )
        """))
        conn.execute(text(
            "INSERT INTO admin (username, password_hash, role) "
            "VALUES ('alice', 'h', 'admin'), ('bob', 'h', 'manager')"
        ))
    return engine


def test_migration_renames_table_and_backfills(old_db):
    from app_migrations import migrate_admin_to_user
    migrate_admin_to_user(old_db)
    insp = inspect(old_db)
    assert 'user' in insp.get_table_names()
    assert 'admin' not in insp.get_table_names()
    cols = {c['name'] for c in insp.get_columns('user')}
    assert 'role' not in cols
    assert 'is_admin' in cols
    assert 'is_league_operator' in cols
    with old_db.begin() as conn:
        rows = conn.execute(text(
            "SELECT username, is_admin, is_league_operator FROM user ORDER BY username"
        )).fetchall()
    assert rows == [('alice', 1, 0), ('bob', 0, 1)]
