"""翻訳結果（translated_text列）を機械的に検証するProgram。

`06_02_review_translation.md`（校正者）向けに、怪しい行を自動検出して
`<論文名>_translation_flags.csv`へ出力する。`05_01_split_sentences.md`の`find_flags`と
同じ考え方（決定論的に検出できるものはPythonで拾い、LLMは判断が必要な箇所に集中する）。

使い方:
    python postprocess/src/check_translation.py output/paper/paper.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 翻訳対象のtype。referenceは翻訳しない方針（05_02_review_split.md以降と同じCSV仕様）。
TRANSLATABLE_TYPES = {"heading", "body", "caption", "footnote"}

MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]+?\$", re.DOTALL)
# 原文中の引用番号（例: [&#91;13&#93;](#page-10-0) や [13](...)）から番号だけを取り出す。
CITATION_NUMBER_RE = re.compile(r"(?:&#91;|\[)\s*(\d+)\s*(?:&#93;|\])")
JAPANESE_CHAR_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")


@dataclass
class Flag:
    order: str
    sentence_id: str
    type: str
    reason: str
    detail: str


def _math_spans(text: str) -> list[str]:
    return MATH_RE.findall(text)


def _citation_numbers(text: str) -> list[str]:
    return CITATION_NUMBER_RE.findall(text)


def check_row(row: dict[str, str]) -> list[str]:
    """1行分のチェックを行い、reasonのリストを返す（問題が無ければ空リスト）。"""
    reasons: list[str] = []
    original = row["original_text"]
    translated = row["translated_text"]

    if row["type"] == "reference":
        if translated.strip():
            reasons.append("reference_should_not_be_translated")
        return reasons

    if row["type"] == "image":
        if translated.strip():
            reasons.append("image_should_not_be_translated")
        return reasons

    if row["type"] not in TRANSLATABLE_TYPES:
        return reasons

    if not translated.strip():
        reasons.append("missing_translation")
        return reasons

    if not JAPANESE_CHAR_RE.search(translated):
        reasons.append("no_japanese_detected")

    orig_math = Counter(_math_spans(original))
    trans_math = Counter(_math_spans(translated))
    if orig_math != trans_math:
        reasons.append("math_mismatch")

    orig_citations = set(_citation_numbers(original))
    missing_citations = {n for n in orig_citations if n not in translated}
    if missing_citations:
        reasons.append("citation_number_missing")

    return reasons


def find_flags(rows: list[dict[str, str]]) -> list[Flag]:
    flags: list[Flag] = []
    for row in rows:
        for reason in check_row(row):
            detail = row["translated_text"][:80] or "(空欄)"
            flags.append(
                Flag(
                    order=row["order"],
                    sentence_id=row["sentence_id"],
                    type=row["type"],
                    reason=reason,
                    detail=detail,
                )
            )
    return flags


FLAGS_CSV_HEADER = ["order", "sentence_id", "type", "reason", "detail"]


def write_flags_csv(flags: list[Flag], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FLAGS_CSV_HEADER)
        for flag in flags:
            writer.writerow([flag.order, flag.sentence_id, flag.type, flag.reason, flag.detail])


def check_translation(csv_path: Path, output_path: Path | None = None) -> tuple[Path, int]:
    output_path = output_path or csv_path.with_name(csv_path.stem + "_translation_flags.csv")
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    flags = find_flags(rows)
    write_flags_csv(flags, output_path)
    return output_path, len(flags)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="検証対象のCSV（<論文名>.csv）")
    parser.add_argument("--output", type=Path, default=None, help="出力先（省略時は自動decide）")
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"CSVが見つかりません: {args.csv_path}")

    output_path, flag_count = check_translation(args.csv_path, args.output)
    print(f"フラグ: {flag_count}件 -> {output_path}")


if __name__ == "__main__":
    main()
