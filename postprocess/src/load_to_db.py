"""翻訳済みCSVを検証し、DB（Postgres互換）へ保存するProgram。

v0要件定義（`20260909_paper_preprocessing_requirements_v0.md` Step 5・7章）に対応する。
DBスキーマは `postprocess/src/db/models.py`（SQLAlchemy ORM）で定義し、スキーマの
作成・変更はAlembic（`postprocess/migrations/`）で管理する。本Programはテーブルを
作成しない（事前に `alembic upgrade head` を実行しておくこと）。

使い方:
    # 接続情報が無くても、CSVの検証だけ行える
    python postprocess/src/load_to_db.py output/paper/paper.csv --dry-run

    # 実際にDBへ保存する（事前に alembic upgrade head が必要）
    python postprocess/src/load_to_db.py output/paper/paper.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from db.engine import create_db_engine
from db.models import Paper, Sentence
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

REQUIRED_COLUMNS = [
    "paper_id",
    "sentence_id",
    "page_number",
    "order",
    "type",
    "heading_level",
    "original_text",
    "translated_text",
]
# 翻訳対象外（type=reference/image）はtranslated_textが空欄でも欠損とみなさない。
# 05_01_split_sentences.md / 06_01_translate.md と同じtype一覧。
TRANSLATABLE_TYPES = {"heading", "body", "caption", "footnote"}
VALID_TYPES = TRANSLATABLE_TYPES | {"reference", "image"}


def read_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate_csv(rows: list[dict[str, str]]) -> list[str]:
    """v0のStep5検証項目を確認し、エラーメッセージのリストを返す（空なら検証OK）。"""
    errors: list[str] = []

    if not rows:
        return ["CSVにレコードが1件もありません"]

    # CSV形式・必須列の存在確認
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing_columns:
        return [f"必須列が不足しています: {missing_columns}"]

    # paper_idとの対応確認（1つのCSVは1論文分を想定）
    paper_ids = {r["paper_id"] for r in rows}
    if len(paper_ids) != 1:
        errors.append(f"paper_idが単一ではありません: {sorted(paper_ids)}")

    # sentence_idの重複確認
    sentence_id_counts = Counter(r["sentence_id"] for r in rows)
    duplicates = [sid for sid, count in sentence_id_counts.items() if count > 1]
    if duplicates:
        errors.append(f"sentence_idが重複しています: {duplicates}")

    for r in rows:
        sid = r["sentence_id"]

        # 原文欠損の確認
        if not r["original_text"].strip():
            errors.append(f"{sid}: original_textが空欄です")

        # type値の確認
        if r["type"] not in VALID_TYPES:
            errors.append(f"{sid}: typeが不正です（{r['type']!r}）")

        # 翻訳欠損の確認（referenceは対象外）
        if r["type"] in TRANSLATABLE_TYPES and not r["translated_text"].strip():
            errors.append(f"{sid}: translated_textが空欄です（type={r['type']}）")

        # order/heading_level/page_numberの型確認
        if not r["order"].strip().isdigit():
            errors.append(f"{sid}: orderが整数ではありません（{r['order']!r}）")
        if r["heading_level"].strip() and not r["heading_level"].strip().isdigit():
            errors.append(f"{sid}: heading_levelが整数ではありません（{r['heading_level']!r}）")
        if r["page_number"].strip() and not r["page_number"].strip().isdigit():
            errors.append(f"{sid}: page_numberが整数ではありません（{r['page_number']!r}）")

    return errors


def read_drive_file_id(csv_path: Path, paper_id: str) -> str | None:
    """`<論文名>.drive_id`（01-01-fetch-pdfがDrive検索時に記録するサイドカー）を読む。

    CSVと同じ`output/<論文名>/`ディレクトリに置かれる想定。ファイルが無い場合
    （ローカルにのみ存在しDrive検索で見つからなかった場合）はNoneを返す。
    """
    sidecar_path = csv_path.parent / f"{paper_id}.drive_id"
    if not sidecar_path.is_file():
        return None
    content = sidecar_path.read_text(encoding="utf-8").strip()
    return content or None


def derive_title(rows: list[dict[str, str]]) -> str:
    """最初のH1見出し（type=heading, heading_level=1）のテキストをタイトルとする。

    見つからない場合はpaper_idをそのまま使う。
    """
    for r in rows:
        if r["type"] == "heading" and r["heading_level"].strip() == "1":
            return r["original_text"]
    return rows[0]["paper_id"] if rows else ""


def _to_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _to_text(value: str) -> str | None:
    return value if value.strip() else None


def save_to_db(
    session: Session,
    rows: list[dict[str, str]],
    paper_id: str,
    file_name: str,
    title: str,
    processing_status: str,
    drive_file_id: str | None,
) -> int:
    """DBへpapers・sentencesをupsertし、保存後の件数を返す（保存結果の検証用）。"""
    paper_stmt = pg_insert(Paper).values(
        paper_id=paper_id,
        file_name=file_name,
        title=title,
        processing_status=processing_status,
        drive_file_id=drive_file_id,
    )
    paper_stmt = paper_stmt.on_conflict_do_update(
        index_elements=[Paper.paper_id],
        set_={
            "file_name": paper_stmt.excluded.file_name,
            "title": paper_stmt.excluded.title,
            "processing_status": paper_stmt.excluded.processing_status,
            "drive_file_id": paper_stmt.excluded.drive_file_id,
        },
    )
    session.execute(paper_stmt)

    sentence_values = [
        {
            "sentence_id": r["sentence_id"],
            "paper_id": r["paper_id"],
            "sentence_order": _to_int(r["order"]),
            "page_number": _to_int(r["page_number"]),
            "type": r["type"],
            "heading_level": _to_int(r["heading_level"]),
            "original_text": r["original_text"],
            "translated_text": _to_text(r["translated_text"]),
        }
        for r in rows
    ]
    sentence_stmt = pg_insert(Sentence).values(sentence_values)
    sentence_stmt = sentence_stmt.on_conflict_do_update(
        index_elements=[Sentence.sentence_id],
        set_={
            "sentence_order": sentence_stmt.excluded.sentence_order,
            "page_number": sentence_stmt.excluded.page_number,
            "type": sentence_stmt.excluded.type,
            "heading_level": sentence_stmt.excluded.heading_level,
            "original_text": sentence_stmt.excluded.original_text,
            "translated_text": sentence_stmt.excluded.translated_text,
        },
    )
    session.execute(sentence_stmt)

    session.commit()

    saved_count = session.scalar(
        select(func.count()).select_from(Sentence).where(Sentence.paper_id == paper_id)
    )
    return saved_count or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="保存対象のCSV（<論文名>.csv）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="CSVの検証のみ行い、DBへは接続・保存しない",
    )
    parser.add_argument(
        "--status",
        default="translated",
        help="papersテーブルのprocessing_status列に設定する値（デフォルト: translated）",
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"CSVが見つかりません: {args.csv_path}")

    rows = read_csv(args.csv_path)
    errors = validate_csv(rows)
    if errors:
        print("検証エラー:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    print(f"検証OK: {len(rows)}行")

    if args.dry_run:
        print("--dry-run のため、DBへの保存はスキップしました")
        return

    paper_id = rows[0]["paper_id"]
    file_name = f"{paper_id}.pdf"
    title = derive_title(rows)
    drive_file_id = read_drive_file_id(args.csv_path, paper_id)

    try:
        engine = create_db_engine()
        with Session(engine) as session:
            saved_count = save_to_db(
                session, rows, paper_id, file_name, title, args.status, drive_file_id
            )
    except RuntimeError as e:
        # create_db_engine()が接続文字列未設定時に送出するエラー
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except SQLAlchemyError as e:
        print(f"エラー: DB操作に失敗しました: {e}", file=sys.stderr)
        print(
            "テーブルが未作成の場合は `cd postprocess && alembic upgrade head` を実行してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"保存完了: paper_id={paper_id!r}, title={title!r}, drive_file_id={drive_file_id!r}")
    print(f"保存件数の検証: CSV {len(rows)}行 -> DB {saved_count}件", end="")
    if saved_count == len(rows):
        print(" (一致)")
    else:
        print(" (不一致。既存の他バージョンのレコードが混在している可能性があります)")


if __name__ == "__main__":
    main()
