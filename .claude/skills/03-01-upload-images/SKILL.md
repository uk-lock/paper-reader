---
name: 03-01-upload-images
description: 02-01-extract-pdfが生成した画像（表・図）をGoogle Driveへアップロードし、Markdown中の画像参照をDrive直リンクへ書き換える。LLMの判断を含まない決定論的な実行のみ。04-01-fix-heading-structureが`_review.md`を作成する前に実行する。
---

# Skill: 画像アップロード・URL書き換え

## 目的
`02-01-extract-pdf`が生成した`<論文名>.md`中の画像参照（表・図の両方）をGoogle Driveへアップロードし、ローカル相対パスをDrive直リンクへ書き換える。`04-01-fix-heading-structure`が`<論文名>_review.md`を作成する前に実行する（以降`<論文名>.md`は差分確認の基準として変更しないため）。本Skill自体はLLMによる判断を含まない、決定論的な実行のみ。

## 前提
- `rclone`がGoogle Drive宛に読み書き両対応のスコープ（`drive`）でOAuth認可済みであること（`01-01-fetch-pdf`のダウンロード専用スコープでは書き込めない）
- `config/settings.toml`の`[gdrive].remote`、`config/settings.local.toml`の`[gdrive].images_folder_id`（画像置き場の共有フォルダID）が設定済みであること
- 画像置き場の共有フォルダは「リンクを知っている人は閲覧可」に設定済みであること
- リポジトリルートの`Makefile`の`make upload-images`ターゲットで、軽量venv（`postprocess/.venv`）の作成〜実行まで1コマンドで完結。Dockerは使用しない

## 入出力
- 入力: `<OUT>/<論文名>/<論文名>.md`（`tables/`フォルダの表画像・同ディレクトリ直下の図画像を含む）
- 出力: `<OUT>/<論文名>/<論文名>.md`（画像参照をDrive直リンクへ書き換え。上書き）。Google Drive側の共有フォルダ直下`<論文名>/`にも画像がアップロードされる

## 手順
1. リポジトリルートで以下を実行する。

   ```bash
   make upload-images MD=output/<論文名>/<論文名>.md
   ```

2. コマンドの終了コードが0であることを確認
3. 標準出力の「アップロード件数」「書き換え件数」を確認する
4. `<論文名>.md`を開き、画像参照が`https://lh3.googleusercontent.com/d/...`形式のURLになっていることを確認する

## 再実行について
`rclone`は同名ファイルへの上書きアップロードで同一Driveファイル（同じfile_id・同じURL）を更新するため、`02-01-extract-pdf`をやり直した場合に本Skillを再実行しても安全（冪等）。既にURL化済みの画像参照はスキップされる。

## エラー時の対応
- `make upload-images`が非0で終了した場合、標準エラー出力のログから原因（`rclone`のスコープ不足・設定未済・ネットワークエラー等）を特定する。原因調査・修正は本Skillの範囲外とし、人間へ報告
- 手順4の確認項目を満たさない場合も同様に報告

## 完了条件・報告
手順2〜4の確認が全て取れた時点で完了。アップロード件数・書き換え件数を作業ログとして報告する。

## 次のSkill
`04-01-fix-heading-structure` を実行する。
