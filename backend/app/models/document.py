from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Document(TimestampedBase):
    __tablename__ = "documents"

    # NULL campaign_id = global (the bundled SRD)
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(12), default="processing")
    # processing | ready | error
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Chunk(TimestampedBase):
    __tablename__ = "chunks"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)
    section_path: Mapped[str] = mapped_column(String(500), default="")  # "Ch 7 > Grappling"
    text: Mapped[str] = mapped_column(Text)


class EmbeddingConfig(TimestampedBase):
    """Singleton row recording which embedding model/dimension built chunks_vec.

    A model or dimension change invalidates the vector index and requires reindexing.
    """

    __tablename__ = "embedding_config"

    model: Mapped[str] = mapped_column(String(120))
    dim: Mapped[int] = mapped_column(Integer)
