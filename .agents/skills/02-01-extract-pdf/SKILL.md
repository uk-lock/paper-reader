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
   - `extract_pdf.py` のログ出力に、Table数の不一致WARNING（実テーブルのMarkdown箇所数と切り出し画像数の不一致で自動挿入をスキップした旨）が出ているか。有無・内容（切り出し画像名を含む）を作業ログに記録する。処理は決定論的で再実行しても同じ結果になるため、WARNINGは異常ではなく `04-02-fix-tables-figures` への引き継ぎ事項。出ていても完了条件は満たす

## エラー時の対応
- `make extract` が非0で終了した場合、標準エラー出力のログから原因（Docker未起動、依存パッケージ不足等）を特定する。原因調査・修正は本Skillの範囲外とし、人間またはCodex/Claude Codeへ報告
- `<論文名>.md` 未生成、または `<span id="...">` 残存の場合も同様に報告
- Table数の不一致WARNINGは止める理由にならない。報告で止めるのは、再実行や人間対応が必要な上記の場合のみ

## 完了条件・報告
手順3・4の確認が全て取れた時点で完了（Table数不一致WARNINGの有無は問わない）。生成された `<論文名>.md` のパス、Table検出数、WARNINGの有無・内容（切り出し画像名を含む）を作業ログとして報告する。WARNINGがあれば、その内容を `04-02-fix-tables-figures` へ引き継ぐ。

完了条件を満たしていれば確認を挟まず次のSkillへ進む。満たしていない場合は本Skill内の該当手順（またはエラー時の対応）からやり直す。完了条件は満たしているが判断に迷う点・懸念がある場合のみ、その旨を添えて人間またはCodex/Claude Codeに相談する。

## 次のSkill
`03-01-upload-images` を実行する。
