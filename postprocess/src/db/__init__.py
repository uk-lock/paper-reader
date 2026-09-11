"""DB（Postgres互換）とのやり取りに関するモジュール群。

- `models`: SQLAlchemy ORMモデル定義（Paper, Sentence）
- `engine`: 接続文字列の読み込みとEngine/Sessionの生成

スキーマの作成・変更はAlembic（`postprocess/alembic.ini` / `postprocess/migrations/`）で
管理する。本パッケージ自体はテーブルを作成しない。
"""
