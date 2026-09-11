"""接続文字列の読み込みとSQLAlchemy Engineの生成。

接続文字列は `config/settings.local.toml` の `[db].connection_string`（秘密情報、
gitignore対象）から読む。`postgres://`/`postgresql://` 形式は、psycopg3ドライバを
明示するため `postgresql+psycopg://` へ正規化する（Neon等、多くのホスティング
サービスが `postgres://` 形式で払い出すため）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from sqlalchemy import Engine, create_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH = REPO_ROOT / "config" / "settings.toml"
SETTINGS_LOCAL_PATH = REPO_ROOT / "config" / "settings.local.toml"


def load_connection_string() -> str:
    """settings.toml + settings.local.toml の [db].connection_string を読む。"""
    settings: dict = {}
    if SETTINGS_PATH.is_file():
        settings.update(tomllib.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("db", {}))
    if SETTINGS_LOCAL_PATH.is_file():
        local = tomllib.loads(SETTINGS_LOCAL_PATH.read_text(encoding="utf-8")).get("db", {})
        settings.update(local)
    return settings.get("connection_string", "")


def normalize_connection_string(connection_string: str) -> str:
    """`postgres://`/`postgresql://` をSQLAlchemy+psycopg3向けの形式へ正規化する。"""
    for prefix in ("postgres://", "postgresql://"):
        if connection_string.startswith(prefix):
            return "postgresql+psycopg://" + connection_string[len(prefix) :]
    return connection_string


def create_db_engine(connection_string: str | None = None) -> Engine:
    """Engineを生成する。省略時はsettingsから接続文字列を読む。

    接続文字列が空の場合はRuntimeErrorを送出する（呼び出し側で分かりやすく案内するため）。
    """
    connection_string = connection_string or load_connection_string()
    if not connection_string:
        raise RuntimeError(
            "DB接続文字列が未設定です。config/settings.local.toml の "
            "[db].connection_string を設定してください（--dry-run なら不要）。"
        )
    return create_engine(normalize_connection_string(connection_string))
