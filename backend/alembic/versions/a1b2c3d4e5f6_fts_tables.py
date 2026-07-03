"""FTS5 virtual tables for chunk and world-event keyword search

Revision ID: a1b2c3d4e5f6
Revises: f6d9d6f5fbdf
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6d9d6f5fbdf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keyword search over RAG chunks, kept in sync by triggers.
    op.execute(
        "CREATE VIRTUAL TABLE chunks_fts USING fts5("
        "text, section_path, content='chunks', content_rowid='rowid')"
    )
    op.execute(
        "CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN "
        "INSERT INTO chunks_fts(rowid, text, section_path) "
        "VALUES (new.rowid, new.text, new.section_path); END"
    )
    op.execute(
        "CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN "
        "INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path) "
        "VALUES ('delete', old.rowid, old.text, old.section_path); END"
    )
    op.execute(
        "CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN "
        "INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path) "
        "VALUES ('delete', old.rowid, old.text, old.section_path); "
        "INSERT INTO chunks_fts(rowid, text, section_path) "
        "VALUES (new.rowid, new.text, new.section_path); END"
    )
    # Keyword search over the campaign continuity log.
    op.execute(
        "CREATE VIRTUAL TABLE world_events_fts USING fts5("
        "description, content='world_events', content_rowid='rowid')"
    )
    op.execute(
        "CREATE TRIGGER world_events_ai AFTER INSERT ON world_events BEGIN "
        "INSERT INTO world_events_fts(rowid, description) "
        "VALUES (new.rowid, new.description); END"
    )
    op.execute(
        "CREATE TRIGGER world_events_ad AFTER DELETE ON world_events BEGIN "
        "INSERT INTO world_events_fts(world_events_fts, rowid, description) "
        "VALUES ('delete', old.rowid, old.description); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS world_events_ad")
    op.execute("DROP TRIGGER IF EXISTS world_events_ai")
    op.execute("DROP TABLE IF EXISTS world_events_fts")
    op.execute("DROP TRIGGER IF EXISTS chunks_au")
    op.execute("DROP TRIGGER IF EXISTS chunks_ad")
    op.execute("DROP TRIGGER IF EXISTS chunks_ai")
    op.execute("DROP TABLE IF EXISTS chunks_fts")
