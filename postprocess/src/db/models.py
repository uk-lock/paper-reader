"""SQLAlchemy ORMモデル定義（Paper, Sentence）。

`postprocess/src/load_to_db.py`（CSV→DB保存）と、将来の閲覧用アプリの両方から
同じモデル定義を再利用できるようにする。スキーマ変更はここを直接いじるのではなく、
Alembicのマイグレーション（`postprocess/migrations/versions/`）で行う。
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[str] = mapped_column(Text, primary_key=True)
    file_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str | None] = mapped_column(Text)
    # Google Drive上の元PDFのファイルID（Drive APIの一意識別子。パスと違いリネーム・移動でも不変）。
    # ローカルにのみ存在しDrive検索で見つからなかった場合はnull（01-01-fetch-pdf参照）。
    drive_file_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    sentences: Mapped[list[Sentence]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class Sentence(Base):
    __tablename__ = "sentences"
    __table_args__ = (
        UniqueConstraint("paper_id", "sentence_order", name="uq_sentences_paper_order"),
    )

    sentence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    # CSVの`order`列に対応。`order`はSQL予約語のため列名を変えている。
    sentence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text)

    paper: Mapped[Paper] = relationship(back_populates="sentences")


class ReaderAnnotation(Base):
    """GPT Site閲覧時のメモ・マーカー・しおり（1件1行）。

    詳細は `docs/.steering/20260911_paper_reader_site_db_design.md` の4章を参照。
    """

    __tablename__ = "reader_annotations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('note', 'highlight', 'bookmark')", name="ck_reader_annotations_kind"
        ),
        CheckConstraint("view_mode IN ('reading', 'pdf')", name="ck_reader_annotations_view_mode"),
        CheckConstraint(
            "color IS NULL OR color IN ('yellow', 'red', 'blue')",
            name="ck_reader_annotations_color",
        ),
        CheckConstraint("pdf_page IS NULL OR pdf_page >= 1", name="ck_reader_annotations_pdf_page"),
        CheckConstraint("version >= 1", name="ck_reader_annotations_version"),
        CheckConstraint(
            "(view_mode <> 'reading' OR pdf_page IS NULL)"
            " AND (view_mode <> 'pdf' OR sentence_id IS NULL)",
            name="ck_reader_annotations_view_mode_fields",
        ),
        Index("ix_reader_annotations_paper_kind", "paper_id", "kind"),
        Index("ix_reader_annotations_sentence_id", "sentence_id"),
    )

    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    view_mode: Mapped[str] = mapped_column(Text, nullable=False)
    sentence_id: Mapped[str | None] = mapped_column(
        ForeignKey("sentences.sentence_id", ondelete="SET NULL")
    )
    pdf_page: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    selected_text: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class ReaderPosition(Base):
    """論文・閲覧モードごとの最後の読書位置（1論文1モードにつき1行）。

    詳細は `docs/.steering/20260911_paper_reader_site_db_design.md` の5章を参照。
    """

    __tablename__ = "reader_positions"
    __table_args__ = (
        CheckConstraint("view_mode IN ('reading', 'pdf')", name="ck_reader_positions_view_mode"),
        CheckConstraint(
            "sentence_offset IS NULL OR (sentence_offset >= 0 AND sentence_offset <= 1)",
            name="ck_reader_positions_sentence_offset",
        ),
        CheckConstraint("pdf_page IS NULL OR pdf_page >= 1", name="ck_reader_positions_pdf_page"),
        CheckConstraint(
            "pdf_offset IS NULL OR (pdf_offset >= 0 AND pdf_offset <= 1)",
            name="ck_reader_positions_pdf_offset",
        ),
        CheckConstraint("version >= 1", name="ck_reader_positions_version"),
        CheckConstraint(
            "(view_mode <> 'reading' OR (pdf_page IS NULL AND pdf_offset IS NULL))"
            " AND (view_mode <> 'pdf' OR (sentence_id IS NULL AND sentence_offset IS NULL))",
            name="ck_reader_positions_view_mode_fields",
        ),
        Index("ix_reader_positions_sentence_id", "sentence_id"),
    )

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.paper_id", ondelete="CASCADE"), primary_key=True
    )
    view_mode: Mapped[str] = mapped_column(Text, primary_key=True)
    sentence_id: Mapped[str | None] = mapped_column(
        ForeignKey("sentences.sentence_id", ondelete="SET NULL")
    )
    sentence_offset: Mapped[float | None] = mapped_column(Double)
    pdf_page: Mapped[int | None] = mapped_column(Integer)
    pdf_offset: Mapped[float | None] = mapped_column(Double)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
