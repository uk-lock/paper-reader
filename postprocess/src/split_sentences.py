"""<論文名>_review.md を文単位に分割し、CSVへ出力するProgram。

パイプラインの Step 5（文章分割・CSV出力）に対応する。

- 見出し・図表キャプション・参照文献リスト・画像参照もレコード化する（`type` 列で区別）
- 画像参照（`type=image`）はDrive URL込みのMarkdown画像記法をそのまま`original_text`へ格納する
  （`03-01-upload-images`が事前にローカルパスをURLへ書き換えている前提。翻訳対象外）
- 数式（$...$ / $$...$$）は文中に温存し、内部のピリオドでは分割しない
- page_number は現状取得不可のため空欄のまま出力する（将来 marker-pdf の
  paginate_output を導入した際に埋める想定）

使い方:
    python postprocess/src/split_sentences.py output/paper/paper_review.md
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import pysbd

# marker-pdfが挿入する、元PDF上の位置を指すためだけの空アンカータグ。
# extract_pdf.py側で除去される想定だが、古い成果物には残っている場合があるため
# 本Programでも防御的に除去する（extract_pdf.pyのEMPTY_SPAN_ANCHOR_REと同一パターン）。
EMPTY_SPAN_ANCHOR_RE = re.compile(r'<span id="[^"]*"></span>')

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMAGE_ONLY_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
HR_ONLY_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
CAPTION_RE = re.compile(r"^(Figure|Table)\s+\d+\s*:", re.IGNORECASE)
FOOTNOTE_DEF_RE = re.compile(r"^\[\^(\d+)\]:\s*(.*)$", re.DOTALL)
REFERENCES_HEADING_TEXT = "References"

# pysbdが誤って文境界と誤認しやすい既知の略語。マッチしたピリオドを一時的に
# プレースホルダへ退避してから分割し、分割後に元へ戻す。
ABBREV_RE = re.compile(r"\b(e\.g|i\.e|cf|etc|vs|Fig|Eq|Sec|No|approx)\.", re.IGNORECASE)
ABBREV_PLACEHOLDER = "․"  # ONE DOT LEADER（本文中には通常出現しない）

# $...$ / $$...$$ をpysbdに渡す前に退避し、数式内のピリオドでの誤分割を防ぐ。
MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]+?\$", re.DOTALL)
MATH_PLACEHOLDER_TMPL = "⟦MATH{i}⟧"  # ⟦MATH{i}⟧


@dataclass
class Record:
    order: int
    type: str
    heading_level: int | None
    text: str


@dataclass
class Flag:
    order: int
    type: str
    reason: str
    detail: str


def clean_markdown(markdown_text: str) -> str:
    """分割前のノイズ除去。marker-pdfの空span anchorタグを除去する。"""
    return EMPTY_SPAN_ANCHOR_RE.sub("", markdown_text)


def split_blocks(markdown_text: str) -> list[str]:
    """空行1つ以上で区切られたブロックのリストを返す（前後空白除去済み、空ブロック除外）。"""
    raw_blocks = re.split(r"\n\s*\n", markdown_text)
    return [b.strip() for b in raw_blocks if b.strip()]


def _protect_math(text: str) -> tuple[str, list[str]]:
    store: list[str] = []

    def repl(m: re.Match[str]) -> str:
        store.append(m.group(0))
        return MATH_PLACEHOLDER_TMPL.format(i=len(store) - 1)

    return MATH_RE.sub(repl, text), store


def _restore_math(text: str, store: list[str]) -> str:
    for i, original in enumerate(store):
        text = text.replace(MATH_PLACEHOLDER_TMPL.format(i=i), original)
    return text


def _guard_abbreviations(text: str) -> str:
    return ABBREV_RE.sub(lambda m: m.group(1) + ABBREV_PLACEHOLDER, text)


def _unguard_abbreviations(text: str) -> str:
    return text.replace(ABBREV_PLACEHOLDER, ".")


_segmenter = pysbd.Segmenter(language="en", clean=False)


def split_sentences(paragraph: str) -> list[str]:
    """1段落のテキストを文単位に分割する。

    数式・既知略語のピリオドは一時的に保護し、pysbdによる誤分割を防ぐ。
    段落内の改行（ソフトラップ）は空白へ正規化する。
    """
    normalized = re.sub(r"\s*\n\s*", " ", paragraph).strip()
    protected, math_store = _protect_math(normalized)
    guarded = _guard_abbreviations(protected)

    sentences = []
    for raw in _segmenter.segment(guarded):
        s = _unguard_abbreviations(raw)
        s = _restore_math(s, math_store)
        s = s.strip()
        if s:
            sentences.append(s)
    return sentences


def classify_and_split(blocks: list[str]) -> list[Record]:
    """ブロック列を種別分類しつつ文分割し、通し番号を振ったRecord列を返す。"""
    records: list[Record] = []
    order = 0
    in_references = False

    for block in blocks:
        heading_match = HEADING_RE.match(block)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            in_references = title == REFERENCES_HEADING_TEXT
            order += 1
            records.append(Record(order=order, type="heading", heading_level=level, text=title))
            continue

        if HR_ONLY_RE.match(block):
            # 区切り線（---等）のみのブロックはレコード化しない
            continue

        if IMAGE_ONLY_RE.match(block):
            # 画像参照（表・図の両方）はtype=imageとして1レコード化する。original_textには
            # Markdown画像記法をそのまま格納する（03-01-upload-images書き換え後はDrive URL込み）。
            order += 1
            records.append(Record(order=order, type="image", heading_level=None, text=block))
            continue

        if in_references:
            # 参照文献は段落単位（extract_pdf.py側で1エントリ1段落に整形済み）でレコード化する
            order += 1
            records.append(Record(order=order, type="reference", heading_level=None, text=block))
            continue

        footnote_match = FOOTNOTE_DEF_RE.match(block)
        if footnote_match:
            # extract_pdf.pyが集約した脚注定義（[^N]: ...）。マーカーを取り除いた本文を分割する
            for sentence in split_sentences(footnote_match.group(2)):
                order += 1
                records.append(
                    Record(order=order, type="footnote", heading_level=None, text=sentence)
                )
            continue

        block_type = "caption" if CAPTION_RE.match(block) else "body"
        for sentence in split_sentences(block):
            order += 1
            records.append(Record(order=order, type=block_type, heading_level=None, text=sentence))

    return records


# 05_02_review_split.md（LLMレビュー）向けの自動フラグ検出。決定論的なヒューリスティックのみを
# 扱い、判定に迷う場合は「見逃すより多めにフラグを立てる」側に倒す（false positiveは許容し、
# 最終判断はLLMに委ねる）。heading・referenceは正常でも短文・句読点なしが普通なので対象外。
FLAG_TARGET_TYPES = {"body", "caption", "footnote"}
FLAG_MIN_LENGTH = 20
# 文末として妥当な終端文字。ピリオド等に加え、$（数式の終端）・)"'等も許容する。
SENTENCE_END_CHARS = set(".!?:;)\"'”’$")


def find_flags(records: list[Record]) -> list[Flag]:
    """怪しいレコードを検出する（LLMレビューが確認すべき候補の絞り込み）。

    - order欠番・重複（分類ロジック自体のバグの兆候）
    - 数式デリミタの不整合（$の数が奇数 = 数式の途中で分割された疑い）
    - 短すぎる断片（文分割の誤爆やページ跨ぎ分断の疑い）
    - 終端句読点が無い（同上。ページ跨ぎ分断の典型パターン）
    """
    flags: list[Flag] = []

    expected_orders = list(range(1, len(records) + 1))
    actual_orders = [r.order for r in records]
    if actual_orders != expected_orders:
        flags.append(
            Flag(
                order=0,
                type="",
                reason="order_not_sequential",
                detail=f"orders={actual_orders[:10]}",
            )
        )

    for r in records:
        if r.type not in FLAG_TARGET_TYPES:
            continue

        text = r.text
        if text.replace("$$", "").count("$") % 2 != 0:
            flags.append(
                Flag(
                    order=r.order, type=r.type, reason="unbalanced_math_delimiter", detail=text[:80]
                )
            )
        if len(text) < FLAG_MIN_LENGTH:
            flags.append(Flag(order=r.order, type=r.type, reason="too_short", detail=text))
        if text and text[-1] not in SENTENCE_END_CHARS:
            flags.append(
                Flag(
                    order=r.order, type=r.type, reason="no_terminal_punctuation", detail=text[-60:]
                )
            )

    return flags


FLAGS_CSV_HEADER = ["order", "type", "reason", "detail"]


def write_flags_csv(flags: list[Flag], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FLAGS_CSV_HEADER)
        for flag in flags:
            writer.writerow([flag.order, flag.type, flag.reason, flag.detail])


CSV_HEADER = [
    "paper_id",
    "sentence_id",
    "page_number",
    "order",
    "type",
    "heading_level",
    "original_text",
    "translated_text",
]


def write_csv(records: list[Record], paper_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for r in records:
            sentence_id = f"{paper_id}-{r.order:05d}"
            writer.writerow(
                [
                    paper_id,
                    sentence_id,
                    "",  # page_number: v1では未対応
                    r.order,
                    r.type,
                    r.heading_level if r.heading_level is not None else "",
                    r.text,
                    "",  # translated_text: Step5で埋める
                ]
            )


def derive_paper_id(review_md_path: Path) -> str:
    stem = review_md_path.stem
    if stem.endswith("_review"):
        return stem[: -len("_review")]
    return stem


def split_review_markdown(
    review_md_path: Path,
    paper_id: str | None = None,
    output_path: Path | None = None,
) -> tuple[Path, Path, int]:
    """review.mdを分割してCSVへ出力する。

    (CSV出力先パス, フラグCSV出力先パス, フラグ件数) を返す。
    フラグCSVは `05_02_review_split.md` がLLMレビュー対象を絞り込むための入力。
    """
    paper_id = paper_id or derive_paper_id(review_md_path)
    output_path = output_path or review_md_path.with_name(f"{paper_id}.csv")
    flags_path = output_path.with_name(f"{paper_id}_flags.csv")

    markdown_text = clean_markdown(review_md_path.read_text(encoding="utf-8"))
    blocks = split_blocks(markdown_text)
    records = classify_and_split(blocks)
    write_csv(records, paper_id, output_path)

    flags = find_flags(records)
    write_flags_csv(flags, flags_path)

    return output_path, flags_path, len(flags)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_md_path", type=Path, help="分割対象の<論文名>_review.md")
    parser.add_argument(
        "--paper-id", type=str, default=None, help="paper_id（省略時はファイル名から自動導出）"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力CSVパス（省略時は入力と同ディレクトリの<paper_id>.csv）",
    )
    args = parser.parse_args()

    if not args.review_md_path.is_file():
        parser.error(f"入力Markdownが見つかりません: {args.review_md_path}")

    output_path, flags_path, flag_count = split_review_markdown(
        args.review_md_path, args.paper_id, args.output
    )
    print(f"完了: {output_path}")
    print(f"フラグ: {flag_count}件 -> {flags_path}")


if __name__ == "__main__":
    main()
