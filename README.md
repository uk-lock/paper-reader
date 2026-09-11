# paper-reader

英語論文PDFを読解しやすい形に前処理するツール。抽出・翻訳・DB格納までを担当。

## 1. ツールの概要

GPT Site上で、論文の原文と日本語訳を行き来しながら読める論文読解支援ツールの一部として、
本リポジトリは以下を担当する。

> 論文PDFから本文を抽出し、文単位に分割・レビューし、日本語へ翻訳して、閲覧用DBへ渡すところまで

処理はSkill（LLMによる判断が必要な工程）とProgram（決定論的に実行できる工程）に分離している。
全体のワークフローは[docs/01_workflow.md](docs/01_workflow.md)、DBスキーマは[docs/03_db.md](docs/03_db.md)、
中間CSVの列定義は[docs/02_csv-schema.md](docs/02_csv-schema.md)を参照。

## 2. 本リポジトリの立ち位置

GPT Site側の閲覧・表示UIは本リポジトリの範囲外。DBスキーマを共有インターフェースとして、
閲覧アプリ側から参照される想定。

```mermaid
flowchart LR
    A["論文PDF"]

    subgraph repo["paper-reader（本repo）"]
        P(["抽出・分割・翻訳・DB格納"]):::here
    end

    C[("DB<br/>papers / sentences")]
    D["GPT Site<br/>閲覧・表示UI（本リポジトリの範囲外）"]:::outside

    A -- 入力 --> P
    P -- 出力 --> C
    C --> D

    classDef here fill:#E7F0FF,stroke:#3B5BDB,color:#1B2A4A
    classDef outside fill:#F1F3F5,stroke:#868E96,color:#343A40,stroke-dasharray: 4 3
    style repo fill:#F8FAFF,stroke:#3B5BDB
```

## 3. 前提条件

- Claude Code または Codex（本リポジトリのSkill実行に必要。Skillは`.claude/skills/`・`.agents/skills/`に定義）
- Claude CodeへのGoogle Drive MCPコネクタ（プラグイン）追加
- GPT Site（論文の原文・翻訳を閲覧するアプリ。本リポジトリの範囲外だが、前処理結果の閲覧側として必要）
- Postgres互換DB（開発時はNeonを想定）。接続文字列は`config/settings.local.toml`の`[db].connection_string`に設定
- rclone。事前に`rclone config`でGoogle Driveへ読み書き両対応スコープ（`drive`）でOAuth認可済みリモートを
  作成しておくこと（`01-01-fetch-pdf`のPDF取得、`03-01-upload-images`の画像アップロードに使用。
  ダウンロード専用スコープでは画像アップロードができない）。リモート名は`config/settings.toml`の`[gdrive].remote`、
  PDFのDrive上のフォルダパスは`config/settings.local.toml`の`[gdrive].pdf_folder`、
  画像アップロード先の共有フォルダIDは同ファイルの`[gdrive].images_folder_id`に設定
  （共有フォルダは「リンクを知っている人は閲覧可」に設定しておくこと）
- Docker（`preprocess/`のPDF→Markdown抽出〔marker-pdf + PyMuPDF〕用devcontainerイメージビルドに必要。
  `postprocess/`は軽量venv〔uv管理〕のためDocker不要）

## 4. 実行手順例

### 4.1 通常の流れ（Claude Code / Codexに一任する）

1. 対象PDFを`pdf/<論文名>.pdf`に配置する（無くてもよい。無ければ`01-01-fetch-pdf`がGoogle Driveから取得する）
2. Claude Code もしくは Codex に「`pdf/<論文名>.pdf`を処理して」のように指示する

指示を受けたLLMは、[docs/01_workflow.md](docs/01_workflow.md)に定義された`01-01-fetch-pdf`〜`07-01-load-to-db`の
Skillを順番に実行し、PDF取得からDB格納まで通しで進める。

### 4.2 特定の処理だけ切り出したい場合

決定論的な処理（Skillを介さない）は`Makefile`にターゲットとして定義済みなので、直接呼び出せる。

```bash
make extract PDF=pdf/paper.pdf OUT=output   # PDF→Markdown抽出（Docker経由）
make upload-images MD=output/paper/paper.md # 画像をGoogle Driveへアップロード・URL書き換え
make split REVIEW=output/paper/paper_review.md  # レビュー済みMarkdown→CSV
make db-upgrade                                  # DBスキーマを最新へ（Alembic）
make load-db CSV=output/paper/paper.csv  # CSV→DB格納
```

上記以外のターゲット（`lint`/`format`/`format-check`/`clean`/`db-revision`等）を含む一覧は`make help`で確認できる。
詳細は[Makefile](Makefile)を参照。

## 5. フォルダ構成

```
paper-reader/
├── pdf/                  # 処理対象PDFの格納先
├── output/<論文名>/       # 論文ごとの中間成果物（Markdown・CSV・表画像）
├── preprocess/           # PDF→Markdown抽出。marker-pdf + PyMuPDF、Docker/devcontainer経由で実行
│   └── src/extract_pdf.py
├── postprocess/          # 画像アップロード・文分割・翻訳補助・DB格納。軽量venv（uv管理）、Docker不要
│   ├── src/              # upload_images.py / split_sentences.py / apply_translations.py / check_translation.py / load_to_db.py / db/
│   └── migrations/       # Alembicマイグレーション
├── config/               # 接続設定。settings.toml（共有）/ settings.local.toml（秘密情報、gitignore対象）
├── docs/                 # ワークフロー・DBスキーマ・CSVスキーマ等のドキュメント
├── .claude/skills/, .claude/agents/   # Claude Code向けSkill定義・subagent定義
├── .agents/skills/, .codex/agents/    # Codex向けSkill定義・subagent定義（内容は.claude側と対応）
└── Makefile              # 各Programの実行コマンド集
```

## 6. 出力内容

### output/`<論文名>`/ 配下

| ファイル | 内容 |
| --- | --- |
| `<論文名>.md` | PDFからの抽出直後のMarkdown。画像参照はDrive直リンクへ書き換え済み（以降変更しない、差分確認の基準） |
| `<論文名>_review.md` | 見出し構造・数式を修正したレビュー済みMarkdown |
| `<論文名>.csv` | 文単位に分割し、日本語訳を格納した最終CSV（画像参照は`type=image`行として保持。列定義は[docs/02_csv-schema.md](docs/02_csv-schema.md)） |
| `<論文名>_flags.csv` | 文分割レビュー用の自動検出候補（レビュー後は消費済み） |
| `<論文名>_translation_flags.csv` | 翻訳レビュー用の自動検出候補（レビュー後は消費済み） |
| `tables/` | PyMuPDFで切り出した表の画像（Google Driveへのアップロード後もローカルには残る） |

### DB

`<論文名>.csv`を検証した上で、Postgres互換DBの下記テーブルへ格納。
- `papers`（論文単位）
- `sentences`（文単位、原文＋翻訳文）

スキーマ・接続設定・マイグレーション運用は[docs/03_db.md](docs/03_db.md)を参照。
