---
name: 01-01-fetch-pdf
description: 処理対象PDFをローカルの pdf/ に用意する。まずGoogle Driveを検索し、見つかればダウンロードして drive_file_id を記録する。Drive上に無ければローカル既存を使う。パイプラインの最初のステップとして、対象PDFのファイル名が与えられたときに使う。
---

# Skill: PDFの準備（Google Drive検索 → 無ければローカル確認）

## 目的
処理対象PDFを `pdf/` に用意する。まずプライベートなGoogle Driveフォルダを検索して取得し、Drive上に見つからない場合はローカル既存を使う。Drive検索で特定できた場合は、ファイルID（`drive_file_id`）も併せて記録する。

## 前提（初回のみ・人間が事前に実施）
- `rclone` インストール済み
- `rclone config` により、対象Google DriveへアクセスできるリモートがOAuth認可済み
- リモート名が `config/settings.toml` の `[gdrive]` セクションに設定済み
- 対象フォルダのDrive上のパスが `config/settings.local.toml` の `[gdrive]` セクションに設定済み

上記の事前設定が前提。いずれか未設定の場合は、ローカルにPDFが既にあっても実行せず、人間に設定を依頼して報告する。

## 入力
対象PDFのファイル名（例: `hogefuga.pdf`）。呼び出し元（人間またはSkill）から与えられる。

## 手順
1. `config/settings.toml` の `[gdrive].remote` と `config/settings.local.toml` の `[gdrive].pdf_folder` を読み取る
2. 以下のコマンドでGoogle Drive上の対象フォルダ内を検索する

   ```bash
   rclone lsf "<remote>:<pdf_folder>" --include "<ファイル名>" --format "ip"
   ```

   （`--format "ip"`でID+パスを取得。IDは後続手順で`drive_file_id`として必要）

3. 検索結果が1件の場合
   - そのファイルIDを`drive_file_id`として控える
   - 以下でダウンロード（ローカルに既にあっても実行してよい。rcloneは内容が同じならスキップするため無駄が少ない）

     ```bash
     rclone copy "<remote>:<pdf_folder>/<ファイル名>" ./pdf/
     ```

   - ダウンロード後、`pdf/<ファイル名>` の存在と、ファイルサイズが0バイトでないことを確認
   - `output/<論文名>/`ディレクトリを作成した上で（無ければ。`<論文名>`はファイル名から拡張子を除いたもの）、控えた`drive_file_id`を`output/<論文名>/<論文名>.drive_id`に1行のテキストとして書き込む（`07-01-load-to-db`が読み取り`papers.drive_file_id`へ保存する。このディレクトリは通常`02-01-extract-pdf`が作成するが、先に作成しても問題ない）

4. 検索結果が0件の場合
   - `pdf/<ファイル名>` の存在を確認する
   - 存在すればそれを対象PDFとして使う（`drive_file_id`は不明のため`output/<論文名>/<論文名>.drive_id`は書き込まない。無ければ`load_to_db.py`側でnull扱い）
   - 存在しなければ「ローカルにもDrive上にも対象PDFが見つからない」旨を報告して終了

5. 検索結果が2件以上の場合、「対象ファイルが複数見つかり一意に特定できない」旨を候補一覧とともに報告して終了

## 異常系の扱い（いずれも自動判断で処理を進めず、報告して終了する）
- 手順1の設定値がいずれか未設定: 「`config/settings.toml`/`config/settings.local.toml` の設定が不足している」旨を報告（ローカルにPDFが既にあっても実行しない）
- 手順2の検索結果が0件かつローカルにも`pdf/<ファイル名>`が無い: 「ローカルにもDrive上にも対象PDFが見つからない」旨を報告
- 手順2の検索結果が2件以上: 「対象ファイルが複数見つかり一意に特定できない」旨を、候補一覧とともに報告
- 手順3のダウンロード後にファイルサイズが0バイト、またはファイルが存在しない: ダウンロード失敗として報告

## 完了条件・報告
`pdf/<ファイル名>` が有効な状態（存在し0バイトでない）で用意できた時点で完了。ローカル既存を使ったか、Driveから取得したかに加え、`drive_file_id`を記録できたかどうかも作業ログに報告する。

## 次のSkill
`02-01-extract-pdf` を実行する。
