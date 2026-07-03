"""FTS5 index over chat messages for automatic campaign-memory recall

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keyword search over the full chat history, kept in sync by triggers.
    op.execute(
        "CREATE VIRTUAL TABLE messages_fts USING fts5("
        "content, content='messages', content_rowid='rowid')"
    )
    op.execute(
        "CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN "
        "INSERT INTO messages_fts(rowid, content) "
        "VALUES (new.rowid, new.content); END"
    )
    op.execute(
        "CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN "
        "INSERT INTO messages_fts(messages_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); END"
    )
    # Only content edits need reindexing; payload/struck updates keep FTS valid.
    op.execute(
        "CREATE TRIGGER messages_au AFTER UPDATE OF content ON messages BEGIN "
        "INSERT INTO messages_fts(messages_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); "
        "INSERT INTO messages_fts(rowid, content) "
        "VALUES (new.rowid, new.content); END"
    )
    # Backfill anything written before this migration.
    op.execute(
        "INSERT INTO messages_fts(rowid, content) SELECT rowid, content FROM messages"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS messages_au")
    op.execute("DROP TRIGGER IF EXISTS messages_ad")
    op.execute("DROP TRIGGER IF EXISTS messages_ai")
    op.execute("DROP TABLE IF EXISTS messages_fts")
