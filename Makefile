# リポジトリ直下のコマンド集（preprocess/ 配下の処理をラップする）。
# リポジトリルートから実行する想定（`make <target>`）。
#
# 使用例:
#   make extract PDF=pdf/paper.pdf
#   make extract PDF=pdf/paper.pdf OUT=output ARGS="--dpi 200"

REPO_ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PREPROCESS_DIR := $(REPO_ROOT)/preprocess
POSTPROCESS_DIR := $(REPO_ROOT)/postprocess
POSTPROCESS_VENV := $(POSTPROCESS_DIR)/.venv
IMAGE_TAG  := paper-reader-extract:latest
CACHE_VOLUME := paper-reader-model-cache

# lint/format で使うruffのバージョン。人間・Claude Code・Codexいずれが実行しても
# 同じ結果になるよう固定する（設定自体はリポジトリ直下のpyproject.tomlを参照）。
RUFF_VERSION := 0.16.6
RUFF := uvx ruff@$(RUFF_VERSION)

# extract 実行時のデフォルト値。呼び出し時に上書き可能。
#   PDF: 変換対象のPDF（リポジトリルートからの相対パス）
#   OUT: 出力先ディレクトリ（リポジトリルートからの相対パス）
#   ARGS: extract_pdf.py への追加引数（例: --dpi 200 --table-pad 10）
PDF  ?= pdf/paper.pdf
OUT  ?= output
ARGS ?=

# split 実行時のデフォルト値。
#   REVIEW: 分割対象の <論文名>_review.md（リポジトリルートからの相対パス）
REVIEW ?=

# load-db 実行時のデフォルト値。
#   CSV: DBへ保存する <論文名>.csv（リポジトリルートからの相対パス）
CSV ?=

# db-revision 実行時のデフォルト値。
#   MSG: 生成するAlembicマイグレーションの説明文
MSG ?=

.PHONY: help build-preprocess extract clean postprocess-venv split lint format format-check db-upgrade db-revision load-db

help:
	@echo "make build-preprocess                         # preprocess用devcontainerイメージをビルド"
	@echo "make extract PDF=pdf/paper.pdf OUT=output   # extract_pdf.py を実行（終了後コンテナは自動削除）"
	@echo "make split REVIEW=output/example/example_review.md"
	@echo "                                               # split_sentences.py を実行（Docker不要、軽量venv使用）"
	@echo "make db-upgrade                               # Alembicマイグレーションを最新まで適用（venv自動構築）"
	@echo "make db-revision MSG=\"変更内容\"                # db/models.py の変更からマイグレーションを生成"
	@echo "make load-db CSV=output/example/example.csv   # CSVをDBへ保存（事前に db-upgrade が必要）"
	@echo "make lint                                     # ruffでリポジトリ全体をチェック"
	@echo "make format                                   # ruffでリポジトリ全体を自動整形"
	@echo "make format-check                             # 整形が必要な差分が無いか確認（CI/pre-commit用）"
	@echo "make clean                                    # ビルドしたイメージを削除"

## preprocess用のDockerfile経由でdevcontainerイメージをビルドする（変更が無ければキャッシュにより数秒）
build-preprocess:
	docker build -f "$(PREPROCESS_DIR)/.devcontainer/Dockerfile" -t "$(IMAGE_TAG)" "$(REPO_ROOT)"

## preprocess/src/extract_pdf.py をコンテナ内で実行する。
## --rm を付けているため、終了時にコンテナは自動でクリーンアップされる。
extract: build-preprocess
	docker run --rm \
		--user vscode \
		-v "$(REPO_ROOT):/workspaces/paper-reader" \
		-v "$(CACHE_VOLUME):/home/vscode/.cache" \
		-w /workspaces/paper-reader \
		"$(IMAGE_TAG)" \
		bash -lc 'mkdir -p /home/vscode/.cache && python preprocess/src/extract_pdf.py "$(PDF)" --output-dir "$(OUT)" $(ARGS)'

## ビルドしたイメージを削除する（モデルキャッシュのvolumeは残す）
clean:
	docker rmi "$(IMAGE_TAG)" 2>/dev/null || true

## postprocess/.venv が無ければ作成し、依存関係をインストールする（Docker不要）
postprocess-venv:
	@if [ ! -d "$(POSTPROCESS_VENV)" ]; then \
		uv venv "$(POSTPROCESS_VENV)" --python 3.12; \
	fi
	@uv pip install --python "$(POSTPROCESS_VENV)/bin/python" -r "$(POSTPROCESS_DIR)/requirements/requirements.txt"

## postprocess/src/split_sentences.py を軽量venvで実行する（marker-pdf/PyMuPDF不要）。
split: postprocess-venv
	@if [ -z "$(REVIEW)" ]; then echo "REVIEW=<論文名>_review.mdのパスを指定してください（例: make split REVIEW=output/example/example_review.md）" >&2; exit 1; fi
	"$(POSTPROCESS_VENV)/bin/python" "$(POSTPROCESS_DIR)/src/split_sentences.py" "$(REVIEW)" $(ARGS)

## Alembicマイグレーションを最新まで適用する（postprocess/.venvが無ければ自動構築）。
## DBスキーマの作成・変更はこのコマンドで行う（load_to_db.py自体はテーブルを作成しない）。
db-upgrade: postprocess-venv
	cd "$(POSTPROCESS_DIR)" && "$(POSTPROCESS_VENV)/bin/alembic" upgrade head

## postprocess/src/db/models.py の変更からAlembicマイグレーションを生成する。
## 生成されたファイル（postprocess/migrations/versions/配下）は内容を確認してからコミットすること。
db-revision: postprocess-venv
	@if [ -z "$(MSG)" ]; then echo 'MSG="変更内容の説明" を指定してください（例: make db-revision MSG="add xxx column"）' >&2; exit 1; fi
	cd "$(POSTPROCESS_DIR)" && "$(POSTPROCESS_VENV)/bin/alembic" revision --autogenerate -m "$(MSG)"

## postprocess/src/load_to_db.py を軽量venvで実行し、CSVをDBへ保存する。
## 事前に db-upgrade でスキーマを用意しておくこと。
load-db: postprocess-venv
	@if [ -z "$(CSV)" ]; then echo "CSV=<論文名>.csvのパスを指定してください（例: make load-db CSV=output/example/example.csv）" >&2; exit 1; fi
	"$(POSTPROCESS_VENV)/bin/python" "$(POSTPROCESS_DIR)/src/load_to_db.py" "$(CSV)" $(ARGS)

## ruffでリポジトリ全体をチェックする（設定はpyproject.toml）。uvxがruffを自動取得するため事前インストール不要。
lint:
	$(RUFF) check .

## ruffでリポジトリ全体を自動整形する（フォーマット + 安全な自動修正）。
format:
	$(RUFF) format .
	$(RUFF) check --fix .

## 整形が必要な差分が無いかだけを確認する（ファイルは書き換えない）。pre-commitフックやCIから使う想定。
format-check:
	$(RUFF) format --check .
	$(RUFF) check .
