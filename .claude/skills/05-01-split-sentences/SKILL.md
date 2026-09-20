---
name: 05-01-split-sentences
description: レビュー済みMarkdownを postprocess/src/split_sentences.py で文単位に分割しCSVへ出力する。LLMの判断を含まない決定論的な実行のみ。04-04-fix-formulas（全章）・04-05-review-formulas完了後に使う。
---

# Skill: 文章分割・CSV出力

## 目的
`04-04-fix-formulas`（全章）・`04-05-review-formulas` 完了後の `<論文名>_review.md` を、`postprocess/src/split_sentences.py` を実行して文単位に分割し、CSVへ出力する。本Skill自体はLLMによる判断を含まない、決定論的な実行のみ。

## 前提
リポジトリルートの `Makefile` の `make split` ターゲットで、軽量venv（`postprocess/.venv`）の作成〜実行まで1コマンドで完結。marker-pdf/PyMuPDFは不要なため、Dockerは使用しない。

## 入出力
- 入力: `<OUT>/<論文名>/<論文名>_review.md`
- 出力:
  - `<OUT>/<論文名>/<論文名>.csv`（列: `paper_id, sentence_id, page_number, order, type, heading_level, original_text, translated_text`）
  - `<OUT>/<論文名>/<論文名>_flags.csv`（列: `order, type, reason, detail`。`05-02-review-split`向けの自動検出候補）

## 手順
1. リポジトリルートで以下を実行する。

   ```bash
   make split REVIEW=output/<論文名>/<論文名>_review.md
   ```

2. コマンドの終了コードが0であることを確認
3. 出力先に `<論文名>.csv` と `<論文名>_flags.csv` が生成されていることを確認
4. `<論文名>.csv` を開き、以下を目視確認する
   - `type` 列が `heading` / `body` / `caption` / `image` / `reference` / `footnote` のいずれかになっていること
   - 見出し（`type=heading`）の `heading_level` が元Markdownの`#`数と一致していること
   - 数式を含む行が、数式部分で不自然に分断されていないこと
   - `order` が1始まりの連番で欠番・重複が無いこと

## 既知の限界（v1時点）
- `page_number` は現状空欄（marker-pdfのページ境界情報を保持していないため）
- キャプションでまれに短い断片（例: `(right)`）が独立行になることがある（pysbdの既知のクセ、軽微なため許容）

上記以外に、ページ跨ぎの脚注挿入による文の分断・参照文献の段落連結は `preprocess/src/extract_pdf.py` 側で解決済み。脚注は `fix_footnotes`、参照文献は `fix_references_line_breaks`（番号付き）・`fix_bulleted_references`（箇条書き著者年）・`fix_author_year_references`（箇条書きにならず段落連結された著者年形式。`Surname, I.` 始まりで直前エントリに `(YYYY)` を含む境界で分割）の3種で、3形式に対応。本Skillはその出力（脚注定義 `[^N]: ...` → `type=footnote`、参照文献1エントリ1段落 → `type=reference`）を前提とする。

## エラー時の対応
- `make split` が非0で終了した場合、標準エラー出力のログから原因（`REVIEW`未指定、入力ファイル不在等）を特定する
- 手順3・4の確認項目を満たさない場合、上記「既知の限界」に該当するか確認し、該当しなければ人間へ報告

## 完了条件・報告
手順3・4の確認が全て取れた時点で完了。生成された `<論文名>.csv` のパスと、`type` 別の行数、`<論文名>_flags.csv` のフラグ件数を作業ログとして報告する。

完了条件を満たしていれば確認を挟まず次のSkillへ進む。満たしていない場合は本Skill内の該当手順（またはエラー時の対応）からやり直す。完了条件は満たしているが判断に迷う点・懸念がある場合のみ、その旨を添えて人間に相談する。

## 次のSkill
`05-02-review-split` を1回実行する。
