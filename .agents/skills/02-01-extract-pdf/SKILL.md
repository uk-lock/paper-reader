---
name: 02-01-extract-pdf
description: 対象PDFをmarker-pdf + PyMuPDF経由でMarkdownへ変換する。LLMの判断を含まない決定論的な実行のみ。01-01-fetch-pdf完了後、Markdownへの変換が必要なときに使う。
---

# Skill: PDF抽出（marker-pdf + PyMuPDF）

## 目的
対象PDFをMarkdownへ変換する。`preprocess/src/extract_pdf.py` をコンテナ経由で実行し、`03-01-upload-images` 以降の入力となるMarkdownを生成する。本Skill自体はLLMによる判断を含まない、決定論的な実行のみ。

## 前提
リポジトリルートの `Makefile` の `make extract` ターゲットで、ビルド・実行・コンテナクリーンアップまで1コマンドで完結。

## 入出力
- 入力: 対象PDF（`pdf/` 配下）
- 出力: `<OUT>/<論文名>/<論文名>.md`、`tables/` フォルダ（表画像）、および同ディレクトリ直下の図画像（`_page_<N>_Figure_<M>.jpeg`等。marker-pdfが直接生成）

## 手順
1. リポジトリルートで以下を実行する。

   ```bash
   make extract PDF=pdf/<対象PDFファイル名> OUT=output
   ```

2. コマンドの終了コードが0であることを確認
3. 出力先に `<論文名>.md` が生成されていることを確認
4. `<論文名>.md` を開き、以下を目視確認する
   - `<span id="...">` が残っていないこと（`extract_pdf.py` 側で除去済みのはず）
   - 検出したTable数と、実際に `tables/` フォルダへ保存された画像数の一致（`extract_pdf.py` のログ出力に不一致WARNINGが出ていないこと）

## エラー時の対応
- `make extract` が非0で終了した場合、標準エラー出力のログから原因（Docker未起動、依存パッケージ不足等）を特定する。原因調査・修正は本Skillの範囲外とし、人間またはCodex/Claude Codeへ報告
- 手順4の確認項目を満たさない場合も同様に報告

## 完了条件・報告
手順3・4の確認が全て取れた時点で完了。生成された `<論文名>.md` のパスと、Table検出数を作業ログとして報告する。

## 次のSkill
`03-01-upload-images` を実行する。
