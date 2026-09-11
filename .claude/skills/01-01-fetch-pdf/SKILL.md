---
name: 01-01-fetch-pdf
description: 処理対象PDFをローカルの pdf/ に用意する。既にローカルにあればそれを使い、無ければ設定済みのGoogle Driveフォルダから取得する。パイプラインの最初のステップとして、対象PDFのファイル名が与えられたときに使う。
---

# Skill: PDFの準備（ローカル確認 → 無ければGoogle Driveから取得）

## 目的
処理対象PDFを `pdf/` に用意する。既にローカルにあればそれを使い、無ければプライベートなGoogle Driveフォルダから取得する。

## 前提（初回のみ・人間が事前に実施）
- `rclone` インストール済み
- `rclone config` により、対象Google DriveへアクセスできるリモートがOAuth認可済み
- リモート名が `config/settings.toml` の `[gdrive]` セクションに設定済み
- 対象フォルダのDrive上のパスが `config/settings.local.toml` の `[gdrive]` セクションに設定済み

上記の事前設定が前提。いずれか未設定の場合は実行せず、人間に設定を依頼して報告する。

## 入力
対象PDFのファイル名（例: `hogefuga.pdf`）。呼び出し元（人間またはSkill）から与えられる。

## 手順
1. `pdf/<ファイル名>` の存在を確認
2. 存在する場合、それを対象PDFとして手順終了（Driveへは問い合わせない）
3. 存在しない場合、`config/settings.toml` の `[gdrive].remote` と `config/settings.local.toml` の `[gdrive].pdf_folder` を読み取る
4. 以下のコマンドでDrive上の対象フォルダ内を検索する

   ```bash
   rclone lsf "<remote>:<pdf_folder>" --include "<ファイル名>"
   ```

5. 検索結果が1件の場合、以下でダウンロード

   ```bash
   rclone copy "<remote>:<pdf_folder>/<ファイル名>" ./pdf/
   ```

6. ダウンロード後、`pdf/<ファイル名>` の存在と、ファイルサイズが0バイトでないことを確認

## 異常系の扱い（いずれも自動判断で処理を進めず、報告して終了する）
- 手順3の設定値がいずれか未設定: 「`config/settings.toml`/`config/settings.local.toml` の設定が不足している」旨を報告
- 手順4の検索結果が0件: 「Drive上に対象ファイルが見つからない」旨を報告
- 手順4の検索結果が2件以上: 「対象ファイルが複数見つかり一意に特定できない」旨を、候補パスの一覧とともに報告
- 手順6でファイルサイズが0バイト、またはファイルが存在しない: ダウンロード失敗として報告

## 完了条件・報告
`pdf/<ファイル名>` が有効な状態（存在し0バイトでない）で用意できた時点で完了。ローカル既存を使ったか、Driveから取得したかを作業ログに報告する。

## 次のSkill
`02-01-extract-pdf` を実行する。
