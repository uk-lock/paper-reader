"""SQLAlchemy ORMモデル定義（Paper, Sentence）。

`postprocess/src/load_to_db.py`（CSV→DB保存）と、将来の閲覧用アプリの両方から
同じモデル定義を再利用できるようにする。スキーマ変更はここを直接いじるのではなく、
Alembicのマイグレーション（`postprocess/migrations/versions/`）で行う。
"""

from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[str] = mapped_column(Text, primary_key=True)
    file_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str | None] = mapped_column(Text)
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
