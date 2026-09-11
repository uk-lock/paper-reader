"""抽出Markdown中のローカル画像参照をGoogle Driveへアップロードし、直リンクへ書き換えるProgram。

パイプラインの Step 3（画像アップロード・URL書き換え）に対応する。02-01-extract-pdf完了後、
04-01-fix-heading-structureが`<論文名>_review.md`を作成する前に実行する（以降`<論文名>.md`は
差分確認の基準として変更しないため）。

- `<論文名>.md`中の画像参照（`![alt](path)`。表・図の両方、ローカル相対パスのもののみ対象。
  既にURLになっている行はスキップするため再実行しても安全）を対象にする
- `rclone`経由でGoogle Driveの共有フォルダ（config/settings.local.tomlの
  [gdrive].images_folder_id が指すフォルダ直下、`<paper_id>/`）へアップロードする
- 同名ファイルへの再アップロードは`rclone`が同一Driveファイルを上書き更新するため、
  file_id・URLは変わらない（`extract_pdf.py`をやり直した場合の再実行でも安全）
- Markdown中のローカル画像参照をDrive直リンク（`https://lh3.googleusercontent.com/d/<file_id>`）
  へ書き換える

前提:
- `rclone`がGoogle Drive宛に読み書き両対応のスコープでOAuth認可済みであること
  （`rclone config` の scope を `drive` にしておく。ダウンロード専用スコープでは書き込めない）
- `config/settings.toml`の`[gdrive].remote`、`config/settings.local.toml`の
  `[gdrive].images_folder_id`（共有フォルダのID）が設定済みであること
- 画像を置く共有フォルダは「リンクを知っている人は閲覧可」に設定済みであること
  （個人利用前提でのトレードオフ。詳細は `docs/.steering/` の検討メモを参照）

使い方:
    python postprocess/src/upload_images.py output/paper/paper.md
    python postprocess/src/upload_images.py output/paper/paper.md --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "config" / "settings.toml"
SETTINGS_LOCAL_PATH = REPO_ROOT / "config" / "settings.local.toml"

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
DRIVE_DIRECT_URL_TEMPLATE = "https://lh3.googleusercontent.com/d/{file_id}"


class UploadImagesError(RuntimeError):
    pass


def load_gdrive_settings() -> tuple[str, str]:
    """(rcloneリモート名, images_folder_id) を settings.toml / settings.local.toml から読む。"""
    remote = ""
    if SETTINGS_PATH.is_file():
        remote = (
            tomllib.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            .get("gdrive", {})
            .get("remote", "")
        )
    images_folder_id = ""
    if SETTINGS_LOCAL_PATH.is_file():
        local = tomllib.loads(SETTINGS_LOCAL_PATH.read_text(encoding="utf-8")).get("gdrive", {})
        images_folder_id = local.get("images_folder_id", "")
    if not remote:
        raise UploadImagesError(
            "rcloneのリモート名が未設定です。config/settings.toml の [gdrive].remote を設定してください。"
        )
    if not images_folder_id:
        raise UploadImagesError(
            "画像アップロード先フォルダIDが未設定です。config/settings.local.toml の "
            "[gdrive].images_folder_id を設定してください。"
        )
    return remote, images_folder_id


def find_local_image_refs(markdown_text: str) -> list[tuple[str, str]]:
    """Markdown中の画像参照から、ローカル相対パスのものだけを (alt, path) で返す（重複除去済み）。

    既に `http://`/`https://` のURLになっている行は対象外（再実行時にスキップするため）。
    """
    seen: dict[str, str] = {}
    for alt, path in IMAGE_REF_RE.findall(markdown_text):
        if path.startswith("http://") or path.startswith("https://"):
            continue
        seen.setdefault(path, alt)
    return [(alt, path) for path, alt in seen.items()]


def rclone_upload(remote: str, images_folder_id: str, paper_id: str, local_path: Path) -> None:
    target = f"{remote},root_folder_id={images_folder_id}:{paper_id}/{local_path.name}"
    result = subprocess.run(
        ["rclone", "copyto", str(local_path), target],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UploadImagesError(f"rclone copytoに失敗しました（{local_path}）: {result.stderr}")


def rclone_list_file_ids(remote: str, images_folder_id: str, paper_id: str) -> dict[str, str]:
    """`<paper_id>/`配下の {ファイル名: file_id} を返す。"""
    target = f"{remote},root_folder_id={images_folder_id}:{paper_id}/"
    result = subprocess.run(
        ["rclone", "lsf", target, "--format", "ip"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UploadImagesError(f"rclone lsfに失敗しました（{target}）: {result.stderr}")

    file_ids: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        file_id, _, file_name = line.partition(";")
        file_ids[file_name] = file_id
    return file_ids


def derive_paper_id(md_path: Path) -> str:
    return md_path.stem


def upload_images(
    md_path: Path,
    paper_id: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """`<論文名>.md`中のローカル画像を全てDriveへアップロードし、参照をURLへ書き換える。

    (アップロード対象件数, 書き換え件数) を返す。対象0件の場合は何もしない（再実行時の冪等性）。
    """
    paper_id = paper_id or derive_paper_id(md_path)
    markdown_text = md_path.read_text(encoding="utf-8")

    refs = find_local_image_refs(markdown_text)
    if not refs:
        return 0, 0

    paper_dir = md_path.parent
    local_paths: list[Path] = []
    for _alt, rel_path in refs:
        local_path = paper_dir / rel_path
        if not local_path.is_file():
            raise UploadImagesError(f"Markdownが参照する画像が見つかりません: {rel_path}")
        local_paths.append(local_path)

    # <paper_id>/直下はフラットな構成のため、ファイル名の重複はアップロード先の
    # 上書き事故につながる。事前に検出して停止する。
    name_to_paths: dict[str, list[Path]] = {}
    for p in local_paths:
        name_to_paths.setdefault(p.name, []).append(p)
    duplicates = {name: paths for name, paths in name_to_paths.items() if len(paths) > 1}
    if duplicates:
        detail = ", ".join(
            f"{name}: {[str(p) for p in paths]}" for name, paths in duplicates.items()
        )
        raise UploadImagesError(f"アップロード先でファイル名が重複しています: {detail}")

    if dry_run:
        return len(local_paths), len(refs)

    remote, images_folder_id = load_gdrive_settings()
    for local_path in local_paths:
        rclone_upload(remote, images_folder_id, paper_id, local_path)

    file_ids = rclone_list_file_ids(remote, images_folder_id, paper_id)

    updated_text = markdown_text
    for _alt, rel_path in refs:
        file_name = Path(rel_path).name
        file_id = file_ids.get(file_name)
        if file_id is None:
            raise UploadImagesError(
                f"アップロード後にDrive上でファイルが見つかりません: {file_name}"
            )
        url = DRIVE_DIRECT_URL_TEMPLATE.format(file_id=file_id)
        updated_text = updated_text.replace(f"]({rel_path})", f"]({url})")

    md_path.write_text(updated_text, encoding="utf-8")
    return len(local_paths), len(refs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("md_path", type=Path, help="対象の<論文名>.md（extract_pdf.pyの出力）")
    parser.add_argument(
        "--paper-id", type=str, default=None, help="paper_id（省略時はファイル名から自動導出）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Driveへは接続せず、対象画像・書き換え件数の確認のみ行う",
    )
    args = parser.parse_args()

    if not args.md_path.is_file():
        parser.error(f"入力Markdownが見つかりません: {args.md_path}")

    try:
        upload_count, rewrite_count = upload_images(args.md_path, args.paper_id, args.dry_run)
    except UploadImagesError as e:
        parser.error(str(e))

    if upload_count == 0:
        print("対象のローカル画像参照はありませんでした（既にURL化済み、または画像なし）")
    elif args.dry_run:
        print(f"[dry-run] アップロード対象: {upload_count}件、書き換え対象: {rewrite_count}件")
    else:
        print(f"完了: {upload_count}件アップロード、{rewrite_count}件のMarkdown参照を書き換え")


if __name__ == "__main__":
    main()
