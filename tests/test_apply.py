"""Tests for apply.py's ensure_schema: a fresh clone has no
applications.db (gitignored) and nothing else ever applies data/schema.sql
to create one, so every DB-touching path (this CLI, and the dashboard's
own endpoints) would fail with "no such table" otherwise -- found via a
real end-to-end live-fire run against a genuine fresh clone. See
ARCHITECTURE.md's data model section and LEARNING_LOG.md."""

import sqlite3

import apply


def test_ensure_schema_creates_missing_db(tmp_path):
    db_path = tmp_path / "applications.db"
    assert not db_path.exists()

    apply.ensure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "applications" in tables
    assert "resume_versions" in tables


def test_ensure_schema_is_a_noop_on_existing_data(tmp_path):
    db_path = tmp_path / "applications.db"
    apply.ensure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO applications (company, role_title) VALUES ('Acme', 'Engineer')"
    )
    conn.commit()
    conn.close()

    apply.ensure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT company FROM applications").fetchall()
    conn.close()
    assert rows == [("Acme",)]
