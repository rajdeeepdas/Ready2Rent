"""
Every explicit index in docs/schema.md exists in PostgreSQL. Checked against
pg_indexes on the real test database, so this proves the migration, not the model.
"""

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

# (table, column that must appear in some index definition)
REQUIRED = [
    ("accounts_user", "email"),
    ("accounts_user", "role"),
    ("applications_property", "owner_id"),
    ("applications_application", "status"),
    ("applications_application", "assigned_staff_id"),
    ("applications_application", "homeowner_id"),
    ("applications_application", "created_at"),
    ("applications_applicationstatushistory", "application_id"),
    ("applications_applicationstatushistory", "created_at"),
    ("applications_visit", "application_id"),
    ("applications_visit", "scheduled_for"),
]


def _index_defs(table: str) -> list[str]:
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        return [row[0] for row in cur.fetchall()]


@pytest.mark.parametrize("table,column", REQUIRED, ids=[f"{t}.{c}" for t, c in REQUIRED])
def test_required_index_exists(table, column):
    defs = _index_defs(table)
    assert any(f"({column}" in d or f", {column}" in d or f"({column})" in d for d in defs), (
        f"No index on {table}.{column}. Indexes present:\n" + "\n".join(defs)
    )


def test_ops_queue_composite_index_exists():
    defs = _index_defs("applications_application")
    assert any("application_queue_idx" in d and "status" in d and "created_at DESC" in d for d in defs)


def test_user_email_index_is_unique():
    defs = _index_defs("accounts_user")
    assert any("UNIQUE" in d and "(email)" in d for d in defs)
