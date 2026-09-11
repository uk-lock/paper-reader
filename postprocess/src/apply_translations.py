"""翻訳結果（sentence_id -> translated_text のJSON）をCSVへ安全にマージするProgram。

翻訳はSkill（LLM）が行うが、CSVへの書き戻しはカンマ・引用符等のエスケープが絡むため、
決定論的なProgramとして分離する（v0要件定義の設計原則: 「LLMに任せなくてもよい処理は
Program化する」）。

使い方:
    python postprocess/src/apply_translations.py output/paper/paper.csv translations.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

CSV_FIELDS = [
    "paper_id",
    "sentence_id",
    "page_number",
    "order",
    "type",
    "heading_level",
    "original_text",
    "translated_text",
]

# 翻訳対象外のtype（type=referenceはtranslated_textを空欄のまま維持する方針）。
# ここでは警告のみに留め、書き込み自体は拒否しない（意図的に翻訳したいケースを許容）。
NON_TRANSLATABLE_TYPES = {"reference"}


def apply_translations(csv_path: Path, translations: dict[str, str]) -> tuple[int, list[str]]:
    """CSVへ翻訳結果をマージする。(更新件数, 警告メッセージ一覧) を返す。"""
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    known_ids = {r["sentence_id"] for r in rows}
    unknown_ids = sorted(set(translations) - known_ids)
    if unknown_ids:
        raise ValueError(f"CSVに存在しないsentence_idが指定されました: {unknown_ids}")

    warnings: list[str] = []
    updated = 0
    for row in rows:
        sid = row["sentence_id"]
        if sid not in translations:
            continue
        if row["type"] in NON_TRANSLATABLE_TYPES and translations[sid].strip():
            warnings.append(
                f"{sid}: type={row['type']}（翻訳対象外の想定）にtranslated_textを設定しました"
            )
        row["translated_text"] = translations[sid]
        updated += 1

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    return updated, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="更新対象のCSV（<論文名>.csv）")
    parser.add_argument(
        "translations_json",
        type=Path,
        help='{"sentence_id": "translated_text", ...} 形式のJSONファイル',
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"CSVが見つかりません: {args.csv_path}")
    if not args.translations_json.is_file():
        parser.error(f"翻訳結果JSONが見つかりません: {args.translations_json}")

    translations = json.loads(args.translations_json.read_text(encoding="utf-8"))
    updated, warnings = apply_translations(args.csv_path, translations)

    print(f"更新: {updated}件 -> {args.csv_path}")
    for w in warnings:
        print(f"WARNING: {w}")


if __name__ == "__main__":
    main()
