r"""PDFをMarkdownへ変換するProgram（marker-pdf + PyMuPDF ハイブリッド）。

- 本文・見出し・引用番号などはmarker-pdfの変換結果をそのまま使う
- marker-pdfはCPU・OCR無し（`disable_ocr=True`）で実行する
  （OCRを有効にすると数式ごとにVLM推論が直列で走り、実行時間が非現実的に長くなるため）
- 表（Table）だけは、marker-pdfが検出したbboxを使ってPyMuPDFで元PDFから画像として切り出し、
  Markdown中の該当箇所を画像参照に差し替える
- 数式はLaTeX化されず生テキストのまま残る（後続のLLMレビュー工程で実PDFと見比べて修正する想定）
- 脚注（ページ下部注釈）はmarker-pdfがPDF上の物理的な位置のまま本文フローに差し込むため、
  本文中の1文がTableキャプションや画像を挟んで分断されることがある。これをMarkdown標準の
  脚注記法（`[^N]` / 文末の`[^N]: ...`）に変換して解消する（`fix_footnotes`）
- 上記以外にも、ページ跨ぎで図・表・キャプションを挟んで1文が分断されるケース（脚注が原因で
  ないもの）がある。段落が文末の句読点を持たずに終わり、割り込みブロックを読み飛ばした先が
  小文字始まりで続いている場合に1文とみなして結合し、割り込みブロックは結合後へ移動する
  （`merge_page_break_sentences`）
- 参考文献セクションは、marker-pdfの出力ではページ単位で全エントリが1段落に連結されるため、
  `[N] `の連番境界で1エントリ1段落に分割する（`fix_references_line_breaks`）
- 引用番号リンクのエスケープ済み角括弧（`\[N\]`）は、LaTeX形式のディスプレイ数式区切り
  （`\[ ... \]`）と衝突し、数式対応Markdownプレビューで表示が崩れるため、HTMLエンティティ
  （`&#91;` / `&#93;`）に置き換える（`fix_citation_bracket_escapes`）
- 著者名＋年スタイルの引用リンクのエスケープ済み丸括弧（`\(...\)`）も同様に、LaTeXの
  インライン数式区切り（`\( ... \)`）と衝突してParseErrorの原因になるため、HTMLエンティティ
  （`&#40;` / `&#41;`）に置き換える（`fix_citation_paren_escapes`）
- LaTeXの`sidewaystable`等でPDF内容自体が90度回転して組版された表は、切り出したテーブル
  画像も回転したまま保存されてしまうため、テキスト方向（`dir`）から回転を検出し正立させて
  保存する（`detect_table_rotation` / `crop_table_images`）

使い方:
    python preprocess/src/extract_pdf.py pdf/example.pdf --output-dir output
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import save_output, text_from_rendered
from marker.schema import BlockTypes
from PIL import Image

# 数式の中央揃え表示（パイプテーブル記法で出力される）と実テーブルを区別する条件。
# 実テーブルはヘッダー+区切り行の後に本文データ行が1行以上あり、列数も多い。
# 数式の疑似テーブルはデータ行が0、または列数が1〜2しかない。
MIN_BODY_ROWS = 1
MIN_COLUMNS = 3

PIPE_LINE_RE = re.compile(r"^\|.*\|\s*$")
SEP_LINE_RE = re.compile(r"^\|[\s:|-]+\|\s*$")

# marker-pdfが出力する、元PDF上の位置を指すためだけの空アンカータグ。
# 中身入りの<span>や<sup>タグ、通常の引用リンク[..](#..)は対象外。
EMPTY_SPAN_ANCHOR_RE = re.compile(r'<span id="[^"]*"></span>')
EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def remove_span_anchors(markdown_text: str) -> str:
    """marker-pdfが挿入する空の<span id="...">アンカーを除去する。

    除去によって生じた3行以上の連続空行は2行に圧縮する。
    """
    text = EMPTY_SPAN_ANCHOR_RE.sub("", markdown_text)
    return EXCESS_BLANK_LINES_RE.sub("\n\n", text)


# 脚注定義段落: 段落の先頭が `<span id="page-P-K"></span><sup>N</sup>` で始まるもの。
# 数式中の上付き文字（例: d<sup>k</sup>）や著者注記（<sup>∗</sup>等、spanを伴わない）とは
# 区別できる（脚注定義には必ずページアンカーspanが直前に付くため）。
FOOTNOTE_DEF_RE = re.compile(
    r'\n\n<span id="page-\d+-\d+"></span><sup>(\d+)</sup>(.+?)\n\n',
    re.DOTALL,
)
# 本文中の脚注参照マーカー（リンク化された上付き文字）。
# 数式の上付き文字は`[...](...)`でリンク化されないため、これとは衝突しない。
INLINE_FOOTNOTE_REF_RE = re.compile(r"\s*\[<sup>(\d+)</sup>\]\(#page-\d+-\d+\)\s*")
_FOOTNOTE_PLACEHOLDER = "\n\n\x00FOOTNOTE_REMOVED\x00\n\n"
# プレースホルダーの直後が小文字始まりの地の文なら、元は1文だったとみなして結合する。
# 画像・表キャプション・見出し・別アンカー等が直後に来る場合は誤結合を避け、そのまま改行を残す。
_CONTINUATION_NEXT_RE = re.compile(r"\A[a-z]")


def fix_footnotes(markdown_text: str) -> str:
    """脚注をMarkdown標準の脚注記法（`[^N]` / `[^N]: ...`）に変換する。

    marker-pdfはページ下部の脚注を、PDF上の物理的な位置のまま本文フローに差し込む。
    このため脚注の本文がTableキャプションや画像参照を挟んで本文中の1文を分断してしまう
    ことがある（例: `...on the` [脚注本文] `Table 3: ...` [画像] `development set...`）。
    脚注定義を本文から抜き出して文末の脚注一覧へ集約し、本文中には`[^N]`のみを残す。
    """
    footnotes: dict[str, str] = {}

    def _capture(match: re.Match) -> str:
        number, text = match.group(1), match.group(2).strip()
        footnotes[number] = text
        return _FOOTNOTE_PLACEHOLDER

    markdown_text = FOOTNOTE_DEF_RE.sub(_capture, markdown_text)

    while _FOOTNOTE_PLACEHOLDER in markdown_text:
        idx = markdown_text.index(_FOOTNOTE_PLACEHOLDER)
        before = markdown_text[:idx]
        after = markdown_text[idx + len(_FOOTNOTE_PLACEHOLDER) :]
        if _CONTINUATION_NEXT_RE.match(after):
            markdown_text = before.rstrip() + " " + after.lstrip()
        else:
            markdown_text = before.rstrip() + "\n\n" + after.lstrip("\n")

    markdown_text = INLINE_FOOTNOTE_REF_RE.sub(lambda m: f"[^{m.group(1)}]", markdown_text)

    if footnotes:
        block = "\n\n---\n\n" + "\n\n".join(
            f"[^{n}]: {footnotes[n]}" for n in sorted(footnotes, key=int)
        )
        markdown_text = markdown_text.rstrip("\n") + block + "\n"

    return markdown_text


REFERENCES_HEADING_RE = re.compile(r"^#+\s+References[ \t]*$", re.MULTILINE)
# 本処理は04_01_fix_heading_structure.md（見出しレベルの整備）より前の生の抽出結果に対して
# 実行されるため、見出しレベルはまだ崩れている可能性がある（例: Referencesが誤ってH1、
# 次章がH4等）。そのため「次に見出しが来るまで」をH2限定にせず、レベル不問で判定する。
NEXT_HEADING_RE = re.compile(r"^#+\s", re.MULTILINE)
BLANK_LINES_RE = re.compile(r"\n\s*\n")


def fix_references_line_breaks(markdown_text: str) -> str:
    """参考文献セクションで、ページ単位に連結された`[1] ... [2] ...`を1エントリ1段落に分割する。

    分割点は「直前のエントリ番号+1」に完全一致する`[N] `のみを採用するため、
    引用文中に偶然現れる`[数字]`との誤爆は起きない。想定した連番が1件も見つからない
    場合は元のテキストをそのまま返す（フォーマットが異なる場合に壊さないため）。
    """
    heading_match = REFERENCES_HEADING_RE.search(markdown_text)
    if not heading_match:
        return markdown_text

    section_start = heading_match.end()
    next_heading_match = NEXT_HEADING_RE.search(markdown_text, section_start)
    section_end = next_heading_match.start() if next_heading_match else len(markdown_text)

    combined = BLANK_LINES_RE.sub(" ", markdown_text[section_start:section_end]).strip()

    split_points = []
    expected = 1
    cursor = 0
    while True:
        marker = f"[{expected}] "
        pos = combined.find(marker, cursor)
        if pos == -1:
            break
        split_points.append(pos)
        cursor = pos + len(marker)
        expected += 1

    if not split_points:
        return markdown_text

    entries = [
        combined[start:end].strip()
        for start, end in zip(split_points, split_points[1:] + [len(combined)], strict=True)
    ]
    new_section_text = "\n\n" + "\n\n".join(entries) + "\n\n"
    return markdown_text[:section_start] + new_section_text + markdown_text[section_end:]


HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
IMAGE_ONLY_LINE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
HR_ONLY_LINE_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
CAPTION_START_RE = re.compile(r"^(Figure|Table)\s+\d+\s*:", re.IGNORECASE)
LOWERCASE_START_RE = re.compile(r"^[a-z]")
# 文末として妥当な終端文字。ピリオド等に加え、$（数式の終端）・)"'等も許容する。
SENTENCE_END_RE = re.compile(r"[.!?:;)\"'”’$]\s*$")
# 段落の続きを探す際に読み飛ばしてよい「割り込みブロック」の上限数。
# 無関係な段落まで延々と結合してしまうのを防ぐための安全弁。
MAX_INTERRUPTOR_BLOCKS = 3


def _is_interruptor_block(block: str) -> bool:
    """文の続きを探す際に読み飛ばしてよいブロックか（画像・図表キャプション・表）。

    本処理はreplace_tables_with_imagesより前に実行されるため、表はまだ画像化されておらず
    生のパイプテーブル記法のままである点に注意。
    """
    first_line = block.splitlines()[0] if block else ""
    return bool(
        IMAGE_ONLY_LINE_RE.match(block)
        or CAPTION_START_RE.match(block)
        or PIPE_LINE_RE.match(first_line)
    )


def merge_page_break_sentences(markdown_text: str) -> str:
    """ページ跨ぎで分断された本文中の1文を、間の図・表・キャプションを後ろへ回して結合する。

    marker-pdfの出力は、PDF上でページを跨いで続く1文が、間に挟まる図・表・キャプションに
    よって2つの段落に分断されることがある（脚注が原因のケースはfix_footnotesが個別に解消
    済みだが、本関数はそれ以外の一般的なケースを扱う。図表を挟まず単純にページ境界だけで
    分断されるケースも対象）。
    「段落が文末の句読点を持たずに終わり、（画像・キャプション・表を読み飛ばした先の）
    次の地の文が小文字始まりで続いている」場合に1文とみなして結合し、間に挟まっていた
    画像・キャプション・表は結合後の段落の直後へ移動する。
    """
    blocks = [b.strip("\n") for b in re.split(r"\n\s*\n", markdown_text)]

    result: list[str] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        stripped = block.strip()

        needs_continuation = (
            stripped
            and not HEADING_LINE_RE.match(stripped)
            and not IMAGE_ONLY_LINE_RE.match(stripped)
            and not HR_ONLY_LINE_RE.match(stripped)
            and not SENTENCE_END_RE.search(stripped)
        )

        if needs_continuation:
            interruptors: list[str] = []
            j = i + 1
            while j < n and len(interruptors) < MAX_INTERRUPTOR_BLOCKS:
                candidate = blocks[j].strip()
                if not _is_interruptor_block(candidate):
                    break
                interruptors.append(blocks[j])
                j += 1

            if j < n:
                continuation = blocks[j].strip()
                if (
                    continuation
                    and LOWERCASE_START_RE.match(continuation)
                    and not HEADING_LINE_RE.match(continuation)
                    and not _is_interruptor_block(continuation)
                ):
                    result.append(stripped + " " + continuation)
                    result.extend(interruptors)
                    i = j + 1
                    continue

        result.append(block)
        i += 1

    return "\n\n".join(result)


def fix_citation_bracket_escapes(markdown_text: str) -> str:
    r"""引用番号リンクのエスケープ済み角括弧（`\[`/`\]`）をHTMLエンティティに置き換える。

    marker-pdfは引用リンクの視覚的な角括弧を`[\[25\]](#anchor)`のように`\[`/`\]`で
    エスケープして出力するが、この2文字の並びはLaTeX形式のディスプレイ数式区切り
    （`\[ ... \]`、`$$...$$`と同義）としても解釈されるため、数式対応のMarkdown
    プレビュー（KaTeX/MathJax系）では引用番号が独立したブロック数式のように表示が
    崩れる。HTMLエンティティ（`&#91;` / `&#93;`）に置き換えれば、Markdownリンクの
    角括弧としては引き続き正しく機能しつつ、数式区切り記号との衝突を避けられる。
    """
    return markdown_text.replace("\\[", "&#91;").replace("\\]", "&#93;")


def fix_citation_paren_escapes(markdown_text: str) -> str:
    r"""引用リンクのエスケープ済み丸括弧（`\(`/`\)`）をHTMLエンティティに置き換える。

    marker-pdfは著者名＋年スタイルの引用リンクのテキスト中の丸括弧を`\(`/`\)`で
    エスケープして出力するが、この2文字の並びはLaTeXのインライン数式区切り
    （`\( ... \)`、`$...$`と同義）としても解釈されるため、数式対応のMarkdown
    プレビュー（KaTeX/MathJax系）でParseErrorが多発する。しかも開き`\(`と閉じ`\)`が
    別々のMarkdownリンクに分かれて出現するため、複数の引用をまたいだ広い範囲を
    数式として解釈しようとしてほぼ確実に構文エラーになる。HTMLエンティティ
    （`&#40;` / `&#41;`）に置き換えれば、Markdownリンクの丸括弧としては引き続き
    正しく機能しつつ、数式区切り記号との衝突を避けられる（`fix_citation_bracket_escapes`
    の丸括弧版）。
    """
    return markdown_text.replace("\\(", "&#40;").replace("\\)", "&#41;")


def build_converter(output_dir: Path) -> tuple[PdfConverter, ConfigParser]:
    config_parser = ConfigParser(
        {
            "output_dir": str(output_dir),
            "output_format": "markdown",
            "mode": "fast",
            "disable_ocr": True,
            "ocr_inline_math": False,
            "use_llm": False,
        }
    )
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
        llm_service=config_parser.get_llm_service(),
    )
    return converter, config_parser


def collect_table_regions(document) -> list[tuple[int, tuple[float, float, float, float]]]:
    """document中のTable blockを(page_id, bbox)のリストとして、出現順に返す。"""
    regions = []
    for page in document.pages:
        for block in page.children or []:
            if block.block_type == BlockTypes.Table:
                regions.append((page.page_id, block.polygon.bbox))
    return regions


def detect_table_rotation(page, clip) -> int:
    """クロップ領域内のテキスト方向から、正立させるための回転角度（度）を返す。

    ページ自体の`/Rotate`属性とは無関係に、LaTeXの`sidewaystable`等で内容そのものが
    90度回転して描画されている表がある。`page.get_text("dict", clip=...)`の各text
    spanの`dir`（文字の進行方向。横書きなら`(1, 0)`）を見て、横書き以外なら正立に
    必要な回転角度を返す（横書き、またはテキストが取得できない場合は0）。
    """
    for block in page.get_text("dict", clip=clip).get("blocks", []):
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            if dy > 0.5:
                return 90
            if dy < -0.5:
                return -90
    return 0


def crop_table_images(
    pdf_path: Path,
    table_regions: list[tuple[int, tuple[float, float, float, float]]],
    images_dir: Path,
    dpi: int,
    pad: float,
) -> list[str]:
    """各Table領域を元PDFから画像として切り出し、保存したファイル名のリストを返す。

    内容が90度回転して組版された表（`detect_table_rotation`が検出）は、切り出し後に
    正立するよう回転してから保存する。
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    image_names = []
    doc = fitz.open(str(pdf_path))
    try:
        for i, (page_id, bbox) in enumerate(table_regions):
            page = doc[page_id]
            x0, y0, x1, y1 = bbox
            clip = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
            pix = page.get_pixmap(clip=clip, dpi=dpi)
            fname = f"table_page{page_id}_{i}.png"
            angle = detect_table_rotation(page, clip)
            if angle == 0:
                pix.save(images_dir / fname)
            else:
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                image.rotate(angle, expand=True).save(images_dir / fname)
            image_names.append(fname)
    finally:
        doc.close()
    return image_names


def find_real_table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Markdown行リストから「実テーブル」とみなせるパイプテーブル領域を検出する。

    数式の中央揃え表示（パイプテーブル記法だがデータ行が無い/列数が少ない）は除外する。
    戻り値は [start, end) の行範囲のリスト（出現順）。
    """
    blocks = []
    i = 0
    while i < len(lines):
        if PIPE_LINE_RE.match(lines[i]):
            start = i
            j = i + 1
            while j < len(lines) and PIPE_LINE_RE.match(lines[j]):
                j += 1
            block_lines = lines[start:j]

            k = 1
            while k < len(block_lines) and SEP_LINE_RE.match(block_lines[k]):
                k += 1
            body_row_count = len(block_lines) - k
            col_count = block_lines[0].count("|") - 1

            if body_row_count >= MIN_BODY_ROWS and col_count >= MIN_COLUMNS:
                blocks.append((start, j))
            i = j
        else:
            i += 1
    return blocks


def replace_tables_with_images(
    markdown_text: str, image_names: list[str], images_subdir: str
) -> str:
    """検出した実テーブルのMarkdown箇所を、対応する画像参照に差し替える。

    「見つかったパイプテーブルブロック」と「切り出した画像」は、件数が一致する場合に限り
    出現順の対応関係を信頼できる。marker-pdfは表によってパイプテーブルとして描画できず
    本文から欠落したり地の文に混入したりすることがあり、この場合は件数が食い違う。
    どのブロックがどの画像に対応するかを機械的に決め打ちすると誤った画像を挿入しかねない
    ため、件数が一致しない場合は自動置換を行わない（安全側に倒す）。対応付けは後続のLLM
    レビュー工程（`04-02-review-tables-figures`）に委ねる。
    """
    lines = markdown_text.split("\n")
    blocks = find_real_table_blocks(lines)

    if len(blocks) != len(image_names):
        print(
            f"WARNING: 検出した実テーブルのMarkdown箇所({len(blocks)}件)と"
            f"切り出した画像({len(image_names)}件)の数が一致しないため、"
            "誤挿入を避けて画像の自動挿入をスキップしました。"
            f" 切り出し済み画像: {', '.join(image_names) if image_names else 'なし'}"
            "（04-02-review-tables-figuresで対応付けてください）。",
            file=sys.stderr,
        )
        return markdown_text

    for idx, (start, end) in reversed(list(enumerate(blocks))):
        lines[start:end] = [f"![table]({images_subdir}/{image_names[idx]})"]

    return "\n".join(lines)


def extract_pdf(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 150,
    table_pad: float = 6.0,
) -> Path:
    """PDFを変換し、表を画像に差し替えたMarkdownを保存する。保存先のMarkdownパスを返す。"""
    t0 = time.time()

    converter, config_parser = build_converter(output_dir)

    document = converter.build_document(str(pdf_path))
    print(f"build_document: {time.time() - t0:.1f}s, pages={len(document.pages)}")

    table_regions = collect_table_regions(document)
    print(f"検出したTable数: {len(table_regions)}")

    renderer = converter.resolve_dependencies(converter.renderer)
    rendered = renderer(document)
    markdown_text, _extension, _images = text_from_rendered(rendered)
    # 脚注の分断解消はspanアンカー（ページ位置マーカー）を手がかりに脚注定義を検出するため、
    # 必ずremove_span_anchorsより先に実行する。
    markdown_text = fix_footnotes(markdown_text)
    markdown_text = remove_span_anchors(markdown_text)
    # 表はまだ画像化されていない（生のパイプテーブル記法）段階で実行する必要がある
    # （merge_page_break_sentencesが表ブロックを割り込みブロックとして認識するため）。
    markdown_text = merge_page_break_sentences(markdown_text)
    markdown_text = fix_references_line_breaks(markdown_text)
    markdown_text = fix_citation_bracket_escapes(markdown_text)
    markdown_text = fix_citation_paren_escapes(markdown_text)

    output_folder = Path(config_parser.get_output_folder(str(pdf_path)))
    base_filename = config_parser.get_base_filename(str(pdf_path))
    save_output(rendered, str(output_folder), base_filename)

    images_dirname = "tables"
    image_names = crop_table_images(
        pdf_path, table_regions, output_folder / images_dirname, dpi, table_pad
    )

    hybrid_markdown = replace_tables_with_images(markdown_text, image_names, images_dirname)
    markdown_path = output_folder / f"{base_filename}.md"
    markdown_path.write_text(hybrid_markdown, encoding="utf-8")

    print(f"完了: {time.time() - t0:.1f}s -> {markdown_path}")
    return markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path, help="変換対象のPDFファイル")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output"), help="出力先ディレクトリ"
    )
    parser.add_argument("--dpi", type=int, default=150, help="表画像のDPI")
    parser.add_argument("--table-pad", type=float, default=6.0, help="表クロップ時の余白（pt）")
    args = parser.parse_args()

    if not args.pdf_path.is_file():
        parser.error(f"PDFが見つかりません: {args.pdf_path}")

    extract_pdf(args.pdf_path, args.output_dir, dpi=args.dpi, table_pad=args.table_pad)


if __name__ == "__main__":
    main()
