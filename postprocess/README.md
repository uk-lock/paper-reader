# postprocess

`preprocess/`（marker-pdf + PyMuPDFによるPDF→Markdown抽出。重い依存・Docker必須）と対になる、軽量な後処理Program格納フォルダ。marker-pdf・PyMuPDF等の重い依存は含まない。

## 画像アップロード・URL書き換え（`upload_images.py`）

`02-01-extract-pdf`完了後の`<論文名>.md`中の画像参照（表・図）をGoogle Driveへアップロードし、ローカル相対パスをDrive直リンクへ書き換える。`03-01-upload-images`が使用。

```bash
make upload-images MD=output/example/example.md
```

- リポジトリルートから実行。`rclone`がGoogle Drive宛に読み書き両対応のスコープ（`drive`）でOAuth認可済みであること
- `config/settings.toml`の`[gdrive].remote`、`config/settings.local.toml`の`[gdrive].images_folder_id`が設定済みであること
- 同名ファイルへの再アップロードは`rclone`が同一Driveファイルを上書き更新するため、file_id・URLは変わらない（再実行しても安全）
- `--dry-run`を付けるとDriveへは接続せず、対象件数の確認のみ行う

## 文章分割・CSV出力（`split_sentences.py`）

`04-01-fix-heading-structure`〜`04-05-spot-check-review` 完了後の `<論文名>_review.md` を文単位に分割し、CSVへ出力。

```bash
make split REVIEW=output/example/example_review.md
```

- リポジトリルートから実行。`postprocess/.venv`（Python 3.12、[uv](https://docs.astral.sh/uv/)使用）が無ければ自動作成し、`requirements/requirements.txt` の依存関係をインストール
- Docker不要
- venvを直接使う場合:

  ```bash
  uv venv postprocess/.venv --python 3.12
  uv pip install --python postprocess/.venv/bin/python -r postprocess/requirements/requirements.txt
  postprocess/.venv/bin/python postprocess/src/split_sentences.py output/example/example_review.md
  ```

## 翻訳（`apply_translations.py` / `check_translation.py`）

`05-01-split-sentences`〜`05-02-review-split`完了後のCSVに対し、`06-01-translate`（翻訳者）・`06-02-review-translation`（校正者）が使用。

- `apply_translations.py`: `{"sentence_id": "translated_text", ...}` 形式のJSONをCSVへ安全にマージ（LLMによるCSV直接編集でカンマ・引用符のエスケープが壊れるのを防ぐ、書き戻し専用Program）

  ```bash
  postprocess/.venv/bin/python postprocess/src/apply_translations.py output/example/example.csv translations.json
  ```

- `check_translation.py`: 翻訳結果を機械チェックし、怪しい行を`<論文名>_translation_flags.csv`へ出力（未翻訳・数式不一致・引用番号欠落等）

  ```bash
  postprocess/.venv/bin/python postprocess/src/check_translation.py output/example/example.csv
  ```

## DB格納（`load_to_db.py` / `db/` / Alembic）

`06-02-review-translation`完了後のCSVを検証し、DB（Postgres互換）へ保存。`07-01-load-to-db`が使用。

- `src/db/models.py`: SQLAlchemy ORMモデル（`Paper`, `Sentence`）。将来の閲覧用アプリからも再利用する想定
- `src/db/engine.py`: 接続文字列の読み込み・Engine生成
- `migrations/`: Alembicによるスキーマのマイグレーション（`alembic.ini`は`postprocess/`直下）
- `src/load_to_db.py`: CSV検証 + UPSERT実行（テーブル自体は作成しない）

接続文字列は`config/settings.local.toml`の`[db].connection_string`（gitignore対象）に設定。

```bash
# スキーマを最新にする（初回・db/models.py変更後。postprocess/.venvが無ければ自動構築）
make db-upgrade

# db/models.py を変更した場合、マイグレーションを生成してから上記を実行する
make db-revision MSG="変更内容の説明"

# CSVをDBへ保存する
make load-db CSV=output/example/example.csv

# 接続情報が無くても、CSVの検証だけ行える
postprocess/.venv/bin/python postprocess/src/load_to_db.py output/example/example.csv --dry-run
```

`sentence_id`/`paper_id`をキーにUPSERTするため、同じCSVを再実行しても安全（冪等）。
