---
name: 06-01-load-to-db
description: 05-02-review-translation完了後のCSVを検証しDB（Postgres互換）へ保存する。LLMの判断を含まない決定論的な実行のみ。パイプラインの最終ステップとして使う。
---

# Skill: DBへの格納

## 目的
`05-02-review-translation`完了後の`<論文名>.csv`を検証し、DB（Postgres互換）へ保存する。本Skill自体はLLMによる判断を含まない、決定論的な実行のみ。

## 前提
- `config/settings.local.toml` の `[db].connection_string` に接続文字列（Postgres互換）が設定済みであること
- 未設定の場合は`--dry-run`でCSVの検証のみ行える（DBへは接続しない）
- テーブルが未作成の場合は先に `cd postprocess && .venv/bin/alembic upgrade head` を実行しておくこと（手順0参照）

## 入出力
- 入力: `<OUT>/<論文名>/<論文名>.csv`
- 入力（任意）: `pdf/<file_name>.drive_id`（`01-01-fetch-pdf`が作成するサイドカーファイル）。存在すればその内容を`papers.drive_file_id`へ保存し、無ければ`drive_file_id`はnullになる
- 出力: DBの`papers`テーブル・`sentences`テーブル（スキーマは`postprocess/src/db/models.py`で定義）

## 手順
### 0. スキーマの用意(初回・スキーマ変更後のみ)
リポジトリルートで以下を実行する（`postprocess/.venv`が無ければ自動構築される）。
```bash
make db-upgrade
```
スキーマ変更が必要になった場合は、`postprocess/src/db/models.py`を編集した上で以下を実行し、生成されたマイグレーション（`postprocess/migrations/versions/`配下）の内容を確認してからコミットする。
```bash
make db-revision MSG="変更内容の説明"
make db-upgrade
```

### 1. CSVの保存
1. リポジトリルートで以下を実行する。

   ```bash
   make load-db CSV=output/<論文名>/<論文名>.csv
   ```

   （接続情報が未設定の場合はまず `postprocess/.venv/bin/python postprocess/src/load_to_db.py <CSV> --dry-run` で検証のみ行う）

2. コマンドの終了コードが0であることを確認する（非0の場合は検証エラーまたはDBエラー。標準エラー出力に詳細が出る）
3. 出力された「保存件数の検証」が一致していることを確認する（CSV行数とDB保存件数が一致）

## 検証項目（Program内で自動実施）
- CSV形式・必須列の存在確認
- `paper_id`が単一であることの確認
- `sentence_id`の重複確認
- 原文（`original_text`）欠損の確認
- 翻訳（`translated_text`）欠損の確認（`type=reference`は対象外）
- `order`/`heading_level`/`page_number`の型確認

## 実装構成
- `postprocess/src/db/models.py`: SQLAlchemy ORMモデル（`Paper`, `Sentence`）。将来の閲覧用アプリからも再利用する想定
- `postprocess/src/db/engine.py`: 接続文字列の読み込み・Engine生成
- `postprocess/migrations/`: Alembicによるスキーマのマイグレーション（`load_to_db.py`自体はテーブルを作成しない）
- `postprocess/src/load_to_db.py`: CSV検証 + UPSERT実行

## スキーマ
```sql
papers(paper_id PK, file_name, drive_file_id, title, processing_status, created_at)
sentences(sentence_id PK, paper_id FK, sentence_order, page_number, type, heading_level, original_text, translated_text)
```
`sentences.sentence_order`はCSVの`order`列に対応する（`order`はSQL予約語のため列名を変えている）。`paper_id`+`sentence_order`にユニーク制約。

## 再実行について
`sentence_id`・`paper_id`をキーにUPSERT（`ON CONFLICT DO UPDATE`）するため、同じCSVを再実行しても重複せず、内容が更新されるだけで安全（冪等）。

## エラー時の対応
- 検証エラーが出た場合、該当する`sentence_id`を`<論文名>.csv`で確認し、原因のSkill（`05-01-translate`/`05-02-review-translation`等）側の課題として報告する
- 「relation does not exist」等のDBエラーの場合、手順0（`make db-upgrade`）が未実行の可能性がある
- 接続エラーの場合、`config/settings.local.toml`の`[db].connection_string`を確認する

## 完了条件・報告
手順2・3の確認が取れた時点で完了。保存した`paper_id`・タイトル・保存件数に加え、`drive_file_id`を保存できたかどうかを作業ログとして報告する。

## 次のSkill
なし（パイプライン完了）。
